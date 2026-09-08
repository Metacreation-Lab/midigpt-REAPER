# -*- coding: utf-8 -*-
"""
REAPER_midigpt_dashboard.py  --  MIDI-GPT control dashboard (ReaImGui)

Single window for the whole MIDI-GPT workflow: server address, SoundFont
template setup, track setup, running infill, and Global Options -- all in
one place instead of separate Action List entries. Each button here just
calls the same entry-point function the standalone action of the same name
already used (REAPER_midigpt_infill.run_midigpt_infill(), etc.) -- no logic
is duplicated, and the standalone actions still work independently (handy
for keyboard shortcuts).

Global Options are stored in the project itself via SetProjExtState/
GetProjExtState (same mechanism REAPER_midigpt_setup_tracks.py already uses
for track ownership) -- they persist across close/reopen of the project.
REAPER_midigpt_infill.py reads from this storage; a project that's never
had the dashboard opened just gets defaults.

Per-track options (density, polyphony, note duration, key signature, etc.)
are stored the same way, keyed by track GUID under track_params_v1, and
REAPER_midigpt_infill.py reads from this storage per track, defaulting to
"off"/unset for any track the dashboard hasn't touched yet.

This window is a script, not an FX -- it doesn't auto-open with a project.
Run this action to open it whenever you want it. Requires the ReaImGui
REAPER extension (Extensions > ReaPack > Browse packages > search
"ReaImGui") -- see README.md.
"""

import sys
import os
import json

from reaper_python import *

sys.path.append(RPR_GetResourcePath() + "/Scripts/ReaTeam Extensions/API")
import imgui

# Reuse the existing action scripts as libraries -- they live in this same
# folder, so they're importable directly. Each already exposes a plain
# run_*() entry point guarded by `if __name__ == "__main__"`, so importing
# them here doesn't trigger anything on its own.
import REAPER_midigpt_infill as infill
import REAPER_midigpt_setup_tracks as setup_tracks
import REAPER_midigpt_set_soundfont_template as set_soundfont_template
import REAPER_midigpt_apply_soundfont_template as apply_soundfont_template

# ---------------------------------------------------------------------------
# Theme -- every color used anywhere in this dashboard is named here, as
# 0xRRGGBBAA. push_theme() (below) maps these onto ImGui's own style slots;
# every other TextColored()/PushStyleColor() call in the file (the MIDI-GPT
# wordmark/logo, per-track Ignored/Autoregressive status, warning/error
# text) references these same named constants instead of its own hardcoded
# hex. Retheming the whole dashboard -- including those ad hoc call sites,
# not just the base ImGui palette -- is always just editing the values in
# this one block.
# ---------------------------------------------------------------------------

THEME_BG = 0x1A0A0AFF               # WindowBg, PopupBg, ScrollbarBg
THEME_BG_CHILD = 0x140808FF         # ChildBg
THEME_BG_TITLE = 0x220C0CFF         # TitleBg
THEME_BG_TITLE_ACTIVE = 0x4D1414FF
THEME_BG_SURFACE = 0x3D1414FF       # Header (a collapsed section's own row)
THEME_BG_FRAME = 0x2A1010FF         # FrameBg -- sliders/combos/inputs at rest
THEME_BG_FRAME_HOVER = 0x3D1717FF
THEME_BG_FRAME_ACTIVE = 0x4D1C1CFF

THEME_ACCENT_DIM = 0x5C1C1CFF       # borders, separators, buttons/scrollbar at rest
THEME_ACCENT_HOVER = 0x7A2424FF     # hovered state for the above
THEME_ACCENT_ACTIVE = 0x992E2EFF    # pressed/active state for the above
THEME_ACCENT = 0xE63946FF           # primary accent -- checkmarks, logo/wordmark
THEME_ACCENT_DEEP = 0xCC3333FF      # SliderGrab at rest
THEME_ACCENT_BRIGHT = 0xE64545FF    # SliderGrabActive, SeparatorActive, and the
                                     # brightest highlight available -- used for
                                     # an Autoregressive track's header text

THEME_TEXT = 0xEDEDEDFF             # normal text
THEME_TEXT_MUTED = 0x808080FF       # de-emphasized -- an Ignored track's header text
THEME_WARNING = 0xFFAA33FF          # non-fatal status (generation still running, etc)
THEME_ERROR = 0xFF6666FF            # truncated/failed

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

EXT_STATE_SECTION = "MIDI-GPT"
GLOBAL_PARAMS_KEY = "global_params_v1"

DEFAULT_GLOBAL_PARAMS = {
    "temperature":          1.0,
    "model_dim":            4,
    "bars_per_step":        1,
    "tracks_per_step":      1,
    "polyphony_hard_limit": 0,
    "density_hard_limit":   0,
    "max_attempts":         3,
    "temp_escalation":      1.0,
    "top_p":                1.0,
    "top_k":                0,
    "mask_p":               0.0,
    "mask_k":               0,
    "seed":                 -1,
    "checks_idx":           3,
    "shuffle":              0,
    "num_candidates":       1,
}

CHECKS_LABELS = ["None", "Novelty Only", "Silence Only", "Both"]
MAX_LOG_LINES = 500

# Fixed height of the console row -- always shown, this exact size,
# regardless of window size. No collapsing, no popout window, no button:
# just a plain read-only text box (see draw_console()). Simple on purpose
# -- a flexible/collapsing console was, on two separate occasions, the
# actual cause of a residual vertical scrollbar on the main window that
# survived several rounds of fixing the surrounding layout math instead.
CONSOLE_ROW_HEIGHT = 130

# Setup never gets compressed below its own comfortable height as the
# window shrinks, and Generate/Tracks never gets compressed below this --
# their controls would otherwise get squeezed to the point of looking (or
# being) broken. Extra window height beyond this combined floor (plus the
# fixed CONSOLE_ROW_HEIGHT) all goes to Generate/Tracks, which has no
# ceiling of its own. This means the window's own enforced minimum height
# (see SetNextWindowSizeConstraints in loop()) MUST stay tall enough that
# the real remaining height can never drop below Setup's own height (see
# SETUP_ROW_COUNT) + this + CONSOLE_ROW_HEIGHT, or Generate/Tracks would
# be asked for less height than they need -- the same class of overflow
# corruption the ##strip_body fix (see draw_track_controls) addresses one
# level down.
CONTENT_MIN_HEIGHT = 320.0

# Estimated window chrome (title bar + outer window padding) NOT included
# in imgui.GetContentRegionAvail(ctx). Only used as measured_window_chrome_h's
# one-frame fallback in loop() (see that global's comment) -- every frame
# after the first uses the real value, GetWindowHeight(ctx) minus
# GetContentRegionAvail(ctx)'s height, instead of this guess.
WINDOW_CHROME_ESTIMATE = 50.0

# Below this window width, loop() switches from the normal "2x2" layout
# (banner+setup share a row, generate+tracks share the next) to a "4x1"
# layout -- banner, setup, generate, and tracks each stacked full-width,
# one per row -- since side-by-side stops being usable much narrower than
# this. A drawing-mode breakpoint only -- NOT a resize floor (see
# MIN_WINDOW_WIDTH below for why it can't also be one).
NARROW_LAYOUT_WIDTH = 700.0

# The window's actual (and only) width floor, in both layouts. This can't
# switch to something bigger in "wide" mode the way min height switches
# per-mode -- if the floor were NARROW_LAYOUT_WIDTH while wide, the window
# could never be dragged narrower than that floor in the first place, so
# it could never actually cross the breakpoint into "narrow" mode: a
# permanent deadlock, since the resize itself always stays clamped to
# whatever floor is currently set.
MIN_WINDOW_WIDTH = 380.0

# Window max height is just this multiple of whatever the min height for
# the current layout works out to -- a placeholder ratio, easy to retune
# once the narrow layout's actually being used day to day.
HEIGHT_MAX_MULTIPLIER = 1.5

# Preferred width of the Generate panel (left column) -- the Tracks mixer
# to its right gets whatever's left, since that one actually wants it (see
# draw_track_controls). Falls back to 40% of the available width instead
# on a narrow window rather than leaving the mixer with no room at all.
# Raised from 380 -- that width left every 2-column Global Options label
# clipped (a 2-column row needs roughly 2x(longest label + a usable
# slider), and several labels here run 30+ characters; see _slider_grid).
GENERATE_PANEL_WIDTH = 460.0

# Setup's row height (MIDI-GPT wordmark to the left, server/model/
# instrument-provisioning controls to its right) needs an explicit number,
# not just "whatever its content needs", since draw_banner() has to know a
# row_h to center the wordmark within, and getting it wrong either clips
# content or leaves a visible gap below the row. draw_setup_panel is
# exactly SETUP_ROW_COUNT widget rows tall (Server, Model, and two rows of
# buttons) -- computed live in loop() via
# imgui.GetFrameHeightWithSpacing(ctx) * SETUP_ROW_COUNT rather than a
# hardcoded pixel guess, which was measurably wrong (left a gap under
# Setup at the guessed height). Also used as the floor draw_setup_panel
# must never need its own internal scrollbar for -- letting it scroll
# internally would overflow this fixed-height child, corrupting this
# ReaImGui build's window stack the same way an unbounded track strip did
# (see the ##strip_body comment in draw_track_controls).
SETUP_ROW_COUNT = 4

# Width of the MIDI-GPT wordmark's child next to Setup -- wide enough for
# MGPT_BANNER's longest line at MGPT_BANNER_FONT_SIZE with margin to spare;
# extra width is just harmless centered padding. Shrunk alongside
# MGPT_BANNER_FONT_SIZE (see that constant) so Setup's own controls still
# have room to fit horizontally at the window's minimum width.
BANNER_CHILD_WIDTH = 340.0

TRACK_PARAMS_KEY = "track_params_v1"

DEFAULT_TRACK_PARAMS = {
    "collapsed":            0,
    "density":              0,
    "min_polyphony_q":      0,
    "max_polyphony_q":      0,
    "min_note_duration_q":  0,
    "max_note_duration_q":  0,
    "key_signature":        0,
    "pitch_range":          0,
    "silence_proportion":   0,
    "pitch_class_set":      0,
    "nomml":                0,
    "autoregressive":       0,
    "ignore":               0,
    # Pitch mask: 0=Off, 1=Scale, 2=Pitch Classes
    "pitch_mask_mode":      0,
    "pitch_mask_scale":     "major",
    "pitch_mask_root":      0,
    "pitch_mask_classes":   0,   # 12-bit bitmask, bit N = pitch class N allowed
    # Pitch mask soft reweight: 0=Off, 1=Uniform, 2=Normal
    "pitch_shape_mode":     0,
    "pitch_shape_min":      48,
    "pitch_shape_max":      72,
    "pitch_shape_mean":     60,
    "pitch_shape_std":      8.0,
    # Remix (variation of existing content)
    "remix_enabled":        0,
    "remix_amount":         0.3,
    "remix_mode":           0,   # 0=Pitch Only, 1=Pitch + Duration
}

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

NOTE_DURATION_LABELS = ["Any", "32nd", "16th", "8th", "Quarter", "Half", "Whole"]
KEY_SIGNATURE_LABELS = [
    "Any", "C Maj", "C# Maj", "D Maj", "D# Maj", "E Maj", "F Maj", "F# Maj",
    "G Maj", "G# Maj", "A Maj", "A# Maj", "B Maj", "C Min", "C# Min", "D Min",
    "D# Min", "E Min", "F Min", "F# Min", "G Min", "G# Min", "A Min", "A# Min",
    "B Min", "No Key",
]
NOMML_LABELS = [
    "Any", "0 (Coarsest)", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10",
    "11 (Finest)", "Expressive",
]

# MIDI-GPT wordmark, shown next to Setup. Fixed font size regardless of
# window size. \uXXXX-escaped (box-drawing characters aren't ASCII) rather
# than a raw byte, since REAPER's embedded Python interpreter reads script
# files as ASCII regardless of a "# -*- coding: utf-8 -*-" header, and a
# raw non-ASCII byte in the source crashes with UnicodeDecodeError.
MGPT_BANNER = (
    "\u2588\u2588\u2588\u2557   \u2588\u2588\u2588\u2557      \u2588\u2588\u2588\u2588\u2588\u2588\u2557   \u2588\u2588\u2588\u2588\u2588\u2588\u2557   \u2588\u2588\u2588\u2588\u2588\u2557              \u2588\u2588\u2588\u2588\u2588\u2588\u2557   \u2588\u2588\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\n"
    "\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2551      \u2588\u2588\u2554\u2550\u2550\u2550\u255d   \u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557  \u255a\u2550\u2588\u2588\u2554\u255d             \u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255d   \u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557 \u255a\u2550\u2550\u2588\u2588\u2554\u2550\u2550\u255d\n"
    "\u2588\u2588\u2554\u2588\u2588\u2588\u2588\u2554\u2588\u2588\u2551      \u2588\u2588\u2551       \u2588\u2588\u2551  \u2588\u2588\u2551    \u2588\u2588\u2551    \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2551  \u2588\u2588\u2588\u2557  \u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d    \u2588\u2588\u2551   \n"
    "\u2588\u2588\u2551\u255a\u2588\u2588\u2554\u255d\u2588\u2588\u2551      \u2588\u2588\u2551       \u2588\u2588\u2551  \u2588\u2588\u2551    \u2588\u2588\u2551    \u255a\u2550\u2550\u2550\u2550\u2550\u2550\u255d  \u2588\u2588\u2551   \u2588\u2588\u2551  \u2588\u2588\u2554\u2550\u2550\u2550\u255d     \u2588\u2588\u2551   \n"
    "\u2588\u2588\u2551 \u255a\u2550\u255d \u2588\u2588\u2551  \u25e2\u2588\u2588\u2588\u2588\u2588\u2557       \u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d  \u2588\u2588\u2588\u2588\u2588\u2557             \u255a\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d  \u2588\u2588\u2551         \u2588\u2588\u2551   \n"
    "\u255a\u2550\u255d     \u255a\u2550\u255d  \u2588\u2588\u2588\u2588\u2588\u2588\u2551       \u255a\u2550\u2550\u2550\u2550\u2550\u255d   \u255a\u2550\u2550\u2550\u2550\u255d              \u255a\u2550\u2550\u2550\u2550\u2550\u255d   \u255a\u2550\u255d         \u255a\u2550\u255d   \n"
    "             \u255a\u2588\u2588\u2588\u2588\u2588\u2554\u255d"
)
# Shrunk from 7.5 -- that size was picked back when this wordmark spanned
# the full window width on its own row; sharing a row with Setup now, it
# needs to be small enough that Setup's controls still fit horizontally
# even at the window's minimum width (see BANNER_CHILD_WIDTH above).
MGPT_BANNER_FONT_SIZE = 5.5

# ---------------------------------------------------------------------------
# Console: writes to both the in-window scrolling log (log_lines, read by
# draw_console below) and a plain log file on disk (LOG_FILE_PATH) -- the
# file survives even if the window's never opened or the console section
# is scrolled away from, the in-window log means no alt-tabbing out to
# read it day to day. Set *after* importing the action modules above (each
# of which sets its own sys.stdout at import time) so this one wins for
# everything printed from here on, regardless of which module's function
# is actually running.
# ---------------------------------------------------------------------------

log_lines = []

# The real, measured height of a "Console"-style SeparatorText row --
# GetCursorPosY() before and after the actual call in loop() (see below),
# not a formula. SeparatorText draws a rule plus text with its own extra
# padding on top of a plain text line, so approximating it via
# GetTextLineHeightWithSpacing() (as earlier rounds did) structurally
# undercounts it -- which is what kept causing a residual scrollbar no
# matter how many *other* spacing terms got fixed. None until the first
# frame finishes; loop() falls back to the old (undercounting, but safe
# to use for exactly one frame) estimate only for that first call.
measured_console_header_h = None

# Same idea, for the window's own chrome (title bar + top/bottom
# WindowPadding): GetWindowHeight() minus GetContentRegionAvail()'s height,
# read right after Begin() -- the actual overhead ImGui reserves outside
# the content area, not the WINDOW_CHROME_ESTIMATE guess. That guess is
# this cache's one-frame fallback (used the first time a given window size
# is ever seen, before Begin() has run once to measure it).
measured_window_chrome_h = None

# The window's actual width, read fresh after Begin() each frame (see
# loop()) and cached here purely so the NEXT frame's pre-Begin
# SetNextWindowSizeConstraints call (which needs to know the layout mode
# before Begin() has even run) can decide between the normal "2x2"
# (banner+setup one row, generate+tracks the next) and the "4x1" narrow
# layout (all four stacked full-width) a frame ahead of time. One frame of
# lag on the mode switch is harmless -- same reasoning as the other
# measured_* caches above.
last_window_w = None

# __file__ isn't an option -- REAPER's embedded Python doesn't set it when
# executing a ReaScript (NameError). RPR_GetResourcePath() (already used
# above for the ReaImGui API path) is the reliable way to locate this
# script's own folder instead: same Scripts/MIDI-GPT directory this file
# and its sibling actions live in, via REAPER's own resource-path API
# rather than Python's normal script-introspection machinery, which
# ReaScript doesn't support.
LOG_FILE_PATH = RPR_GetResourcePath() + "/Scripts/MIDI-GPT/midigpt-dashboard.log"

class _DashboardConsole:
    """Writes to LOG_FILE_PATH (opened once, line-buffered, so a write()
    doesn't pay an open/close per call but still lands on disk promptly)
    and appends completed lines to log_lines for draw_console below."""
    def __init__(self, path):
        self._file = open(path, "a", encoding="utf-8", buffering=1)
        self._buf = ""
    def write(self, s):
        self._file.write(s)
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            log_lines.append(line)
        del log_lines[:-MAX_LOG_LINES]
    def flush(self):
        self._file.flush()

sys.stdout = sys.stderr = _DashboardConsole(LOG_FILE_PATH)
print(f"\n=== MIDI-GPT Dashboard started ===\n")

# ---------------------------------------------------------------------------
# Global Options persistence
# ---------------------------------------------------------------------------

def load_global_params():
    ret, _, _, _, value, _ = RPR_GetProjExtState(0, EXT_STATE_SECTION, GLOBAL_PARAMS_KEY, "", 8192)
    if ret > 0 and value:
        try:
            loaded = json.loads(value)
            params = dict(DEFAULT_GLOBAL_PARAMS)
            params.update({k: v for k, v in loaded.items() if k in DEFAULT_GLOBAL_PARAMS})
            return params
        except Exception as e:
            print(f"Failed to parse saved global params, using defaults: {e}\n")
    return dict(DEFAULT_GLOBAL_PARAMS)

def save_global_params(params):
    RPR_SetProjExtState(0, EXT_STATE_SECTION, GLOBAL_PARAMS_KEY, json.dumps(params))

# ---------------------------------------------------------------------------
# Per-track options persistence -- one JSON blob keyed by track GUID, same
# mechanism as Global Options. Track identity survives track reordering
# since GUIDs (not indices) are the keys.
# ---------------------------------------------------------------------------

def get_track_guid(track):
    return RPR_GetSetMediaTrackInfo_String(track, "GUID", "", False)[3]

def load_track_params():
    ret, _, _, _, value, _ = RPR_GetProjExtState(0, EXT_STATE_SECTION, TRACK_PARAMS_KEY, "", 262144)
    if ret > 0 and value:
        try:
            return json.loads(value)
        except Exception as e:
            print(f"Failed to parse saved track params, starting fresh: {e}\n")
    return {}

def save_track_params(track_params):
    RPR_SetProjExtState(0, EXT_STATE_SECTION, TRACK_PARAMS_KEY, json.dumps(track_params))

# ---------------------------------------------------------------------------
# Active model type -- determines which per-track fields are relevant
# (Yellow/Prism/Expressive have different attribute sets). Detected from the
# server's /info the same way Setup Tracks and Run Infill already do; the
# combo box lets the user override it by hand if the server is unreachable.
# ---------------------------------------------------------------------------

model_type = "yellow"

# Server capabilities, cached alongside model-type detection (both come from
# the same GET /info call) -- gates which advanced per-track controls
# (pitch mask, remix, streaming) draw_track_controls()/run_infill offer,
# since they depend on the loaded checkpoint's encoder config.
server_capabilities = {}
server_scale_presets = ["chromatic", "major", "natural_minor", "harmonic_minor",
                         "melodic_minor", "dorian", "phrygian", "lydian",
                         "mixolydian", "locrian", "major_pentatonic",
                         "minor_pentatonic", "blues", "whole_tone"]

# Available checkpoints from GET /models, and the one to request from
# /generate (persisted via infill.set_selected_model()/ExtState). The
# picker in draw_setup_panel() stays hidden until available_models is
# non-empty -- i.e. until the server has actually been reached and /models
# has answered at least once, per the "only once the server is active"
# requirement. "" for selected_model means "use the server's own
# default_model", which is also what a freshly-installed dashboard starts
# with before the user has ever picked anything.
available_models = []
selected_model = ""

# Live edit buffer for the Setup panel's server-address field -- None until
# first drawn, at which point it's seeded from infill.get_server_url() (see
# draw_setup_panel). Kept separate from that getter's return value so typing
# a new address doesn't get stomped by ExtState on every frame; only
# InputTextFlags_EnterReturnsTrue committing it writes ExtState back.
server_url_input = None

def refresh_model_type():
    """Detects the active model's architecture (Yellow/Prism/Expressive)
    and capabilities via GET /info, and refreshes the list of selectable
    checkpoints via GET /models. Both calls share one server round trip's
    worth of reachability -- if the server can't be reached, the model
    picker simply stays hidden/unchanged rather than showing stale data."""
    global model_type, server_capabilities, server_scale_presets
    global available_models, selected_model
    selected_model = infill.get_selected_model()
    try:
        info = infill.get_server_info(selected_model or None)
        capabilities = info.get("capabilities", {})
        server_capabilities = capabilities
        if capabilities.get("pitch_mask_scale_presets"):
            server_scale_presets = capabilities["pitch_mask_scale_presets"]

        attributes = info.get("attributes", {})
        if "nomml" in attributes:
            model_type = "expressive"
        elif "key_signature" in attributes:
            model_type = "prism"
        else:
            model_type = "yellow"
        print(f"Active model: {model_type.upper()}\n")
    except Exception as e:
        print(f"Could not reach server to detect model type, keeping '{model_type}': {e}\n")

    try:
        models_info = infill.get_available_models()
        available_models = [m["id"] for m in models_info.get("models", []) if m.get("id")]
        default_model = models_info.get("default_model", "")
        if not selected_model and default_model:
            selected_model = default_model
            infill.set_selected_model(selected_model)
        print(f"Available models: {', '.join(available_models) or '(none)'}\n")
    except Exception as e:
        available_models = []
        print(f"Could not reach server to list models: {e}\n")

# ---------------------------------------------------------------------------
# UI: Actions
# ---------------------------------------------------------------------------

last_generation_result = None

# Set while a generation is in flight -- {"handle": GenerationHandle, "ctx": ...}
# from infill.prepare_generation()/start_generation(). Polled once per frame
# in loop(), before Begin(), so the eventual write-back (a REAPER API call)
# never happens mid-ImGui-frame.
active_generation = None

# Set after a num_candidates>1 generation completes -- lets the "swap and
# listen" buttons re-write a different candidate's score without hitting the
# network again. Replaced (old candidates simply forgotten) the moment a new
# generation starts, per the requested lifecycle: swapping is free until the
# next generation, which makes the current pick permanent.
active_batch = None

def start_infill():
    """Non-blocking Run Infill: does REAPER-side prep synchronously (fast,
    local), then hands the slow POST /generate call to a background thread
    so REAPER's UI never freezes waiting on it. loop() polls active_generation
    each frame and finishes the job (including write-back) once it's done."""
    global active_generation, active_batch
    if active_generation is not None:
        print("A generation is already running -- cancel it or wait for it to finish first.\n")
        return

    ctx = infill.prepare_generation()
    if ctx is None:
        return

    num_candidates = ctx["request_dict"]["request"]["config"].get("num_candidates", 1)
    use_streaming = bool(server_capabilities.get("supports_streaming")) and num_candidates == 1

    print("Generating MIDI via MIDI-GPT HTTP server"
          + (" (streaming)" if use_streaming else " (this may take a while)") + "...\n")

    handle = infill.start_generation(ctx["server_url"], ctx["request_dict"], use_streaming)
    active_generation = {"handle": handle, "ctx": ctx}
    active_batch = None

def switch_batch_candidate(idx):
    """Re-writes a different batch candidate's score to REAPER -- instant,
    no network call, since all candidates were already returned by the one
    /generate request. Does nothing for a failed candidate (no score to
    write) or once no batch is active."""
    global active_batch
    if active_batch is None:
        return
    candidates = active_batch["candidates"]
    if not (0 <= idx < len(candidates)):
        return
    cand = candidates[idx]
    if cand.get("score") is None:
        return
    infill.write_generated_score(cand["score"], active_batch["ctx"]["extraction"])
    active_batch["selected"] = idx
    print(f"Switched to candidate {idx + 1} (seed {cand.get('seed')}).\n")

def reset_all_settings():
    """Resets Global Options and Track Controls (per-track generation
    attributes) to their defaults. Deliberately leaves Setup Tracks'
    instrument/SoundFont bookkeeping (track ownership, applied presets)
    untouched -- that's instrument provisioning, a separate concern from
    generation settings, and clearing it would only make Setup Tracks
    redundantly reprocess tracks with no benefit here."""
    global params, track_params
    params = dict(DEFAULT_GLOBAL_PARAMS)
    save_global_params(params)
    track_params = {}
    save_track_params(track_params)
    print("Reset Global Options and Track Controls to defaults. Track instrument/SoundFont setup was left untouched.\n")

ACTIONS = {
    "setup_tracks":            setup_tracks.run_setup_tracks,
    "set_soundfont_template":  set_soundfont_template.run_set_soundfont_template,
    "apply_soundfont_template": apply_soundfont_template.run_apply_soundfont_template,
    "run_infill":              start_infill,
    "refresh_model":           refresh_model_type,
    "reset_all":               reset_all_settings,
}

def draw_setup_panel():
    """One-time-per-project setup: server address, model picker, track/
    instrument provisioning, and reset. These are rarely touched once
    configured, unlike Global Options/Track Controls which get used every
    generation -- kept in their own compact bar above the Generate/Tracks
    panels so they don't compete for space or visual weight with what you
    actually touch every run. Returns the key of whichever ACTIONS entry
    was clicked this frame, or None.
    Callers must NOT invoke it here -- these can be slow (HTTP, generation)
    or open native modal dialogs, and doing that mid-frame (between
    Begin/End) can cause REAPER to repaint with a half-built widget tree,
    corrupting ReaImGui's internal state. Run the returned action only
    after imgui.End() has closed the frame."""
    clicked = None

    global selected_model, server_url_input

    if server_url_input is None:
        server_url_input = infill.get_server_url()

    imgui.Text(ctx, "Server:")
    imgui.SameLine(ctx)
    imgui.SetNextItemWidth(ctx, 240)
    # EnterReturnsTrue -- commit on Enter, not on every keystroke, so a
    # partially-typed URL never gets written to ExtState (and infill.py
    # never tries to hit a half-typed address mid-edit). infill.set_server_url
    # is a plain ExtState write (not a blocking call), so it's safe to run
    # right here rather than through the click-after-End() mechanism this
    # docstring otherwise requires -- same reasoning as set_selected_model
    # below.
    enter, server_url_input = imgui.InputTextWithHint(
        ctx, "##server_url", "http://127.0.0.1:3456", server_url_input,
        imgui.InputTextFlags_EnterReturnsTrue())
    if enter:
        normalized = infill.set_server_url(server_url_input)
        if normalized:
            server_url_input = normalized
            # Re-detect model_type/capabilities/list against whatever
            # server was just pointed at -- otherwise the model picker
            # keeps showing the old server's data until the user notices
            # and clicks 'Refresh##model' themselves. Deferred (unlike the
            # ExtState write above) since it's a blocking HTTP call.
            clicked = "refresh_model"

    # Hidden until refresh_model_type() has successfully reached GET
    # /models at least once -- no point offering a picker backed by a
    # server we haven't actually confirmed is up.
    if available_models:
        imgui.SetNextItemWidth(ctx, 220)
        idx = available_models.index(selected_model) if selected_model in available_models else 0
        c, idx = imgui.Combo(ctx, "Model##checkpoint", idx, "\0".join(available_models) + "\0")
        if c:
            selected_model = available_models[idx]
            infill.set_selected_model(selected_model)
            # Re-detect model_type/capabilities for the newly picked
            # checkpoint. Routed through the click mechanism (run after
            # End(), see this function's docstring) rather than called
            # directly, since it's a blocking HTTP call.
            clicked = "refresh_model"
    else:
        imgui.TextDisabled(ctx, "Model: (checking server...)")

    # No section headers here (Tracks && Instruments / Reset used to each
    # get their own SeparatorText) -- this whole panel now shares its row
    # with the banner instead of having the full window width to itself,
    # and labels plus long button text were what didn't fit. Two rows of
    # two shortened buttons instead of three-then-one keeps every row's
    # width well under what even the smallest allowed window can no longer
    # spare (see BANNER_CHILD_WIDTH). Also, this panel is exactly
    # SETUP_ROW_COUNT widget rows tall (Server, Model, two button rows) --
    # keep that constant in sync if a row is ever added/removed here, since
    # loop() uses it to size this panel's row.
    if imgui.Button(ctx, "Setup Tracks"):
        clicked = "setup_tracks"
    imgui.SameLine(ctx)
    if imgui.Button(ctx, "Set SoundFont Template"):
        clicked = "set_soundfont_template"

    if imgui.Button(ctx, "Apply Template"):
        clicked = "apply_soundfont_template"
    imgui.SameLine(ctx)
    if imgui.Button(ctx, "Reset Controls"):
        clicked = "reset_all"

    return clicked

def _signed32(u32):
    """TextColored takes a signed 32-bit RGBA int; convert from the usual
    0xRRGGBBAA unsigned form."""
    return u32 - 0x100000000 if u32 >= 0x80000000 else u32

def draw_generation_result():
    """While a generation is in flight, shows live progress (streamed note
    count, or a wait message for non-streaming requests) and a Cancel
    button. Once done, shows a formatted summary of the last response
    (seed, token/context usage, speed) plus, for a batch (num_candidates>1)
    result, the candidate swap buttons. Returns the clicked action key
    ("cancel_generation" or "batch_select_N"), or None -- callers must NOT
    act on it here (see draw_setup_panel()'s docstring for why)."""
    if active_generation is not None:
        handle = active_generation["handle"]
        with handle.lock:
            notes = handle.notes_streamed
            stream_mode = handle.stream_mode
            cancel_sent = handle.cancel_sent

        imgui.SeparatorText(ctx, "Generating")
        if stream_mode:
            imgui.Text(ctx, f"Streaming -- {notes} note(s) received so far...")
        else:
            imgui.Text(ctx, "Waiting for the server (non-streaming request)...")

        if cancel_sent:
            imgui.TextDisabled(ctx, "Cancellation requested -- waiting for the server to stop...")
        elif imgui.Button(ctx, "Cancel Generation"):
            return "cancel_generation"
        return None

    if last_generation_result is None:
        return None

    imgui.SeparatorText(ctx, "Last Generation")

    seed = last_generation_result.get("seed")
    elapsed = last_generation_result.get("elapsed")
    tokens = last_generation_result.get("tokens") or {}
    status = last_generation_result.get("status")

    if seed is not None:
        imgui.Text(ctx, f"Seed: {seed}")
    if elapsed is not None:
        imgui.SameLine(ctx)
        imgui.Text(ctx, f"    Time: {elapsed:.2f}s")
    if status and status != "completed":
        imgui.SameLine(ctx)
        imgui.TextColored(ctx, _signed32(THEME_WARNING), f"    [{status}]")

    ctx_tok = tokens.get("context_tokens")
    gen_tok = tokens.get("generated_tokens")
    max_tok = tokens.get("max_context_tokens")
    tps = tokens.get("tokens_per_second")

    if ctx_tok is not None and gen_tok is not None and max_tok:
        # Compute the fraction from the same numbers shown in the overlay
        # text -- the server's own context_utilization field isn't
        # necessarily defined the same way (e.g. context-only, ignoring
        # generated_tokens), which showed up as the bar and the text
        # disagreeing (e.g. "2047/2048" next to "93%").
        used = ctx_tok + gen_tok
        util = max(0.0, min(1.0, used / max_tok))
        overlay = f"{used} / {max_tok} tokens ({util * 100:.0f}%)"
        imgui.ProgressBar(ctx, util, -1, 0, overlay)
        imgui.Text(ctx, f"Context: {ctx_tok} prompt + {gen_tok} generated")

    if tps is not None:
        imgui.Text(ctx, f"Speed: {tps:.1f} tokens/sec")

    if tokens.get("truncated"):
        imgui.TextColored(ctx, _signed32(THEME_ERROR),
                           "Truncated -- hit the context ceiling before finishing (may be cut off mid-bar)")

    clicked = None
    candidates = last_generation_result.get("candidates")
    if candidates:
        imgui.SeparatorText(ctx, "Batch Candidates")
        imgui.TextDisabled(ctx, "Swap freely and listen -- the next generation makes your pick permanent.")
        selected = active_batch.get("selected") if active_batch else last_generation_result.get("selected_index")
        # Wrapped to however many 28px buttons actually fit per row instead
        # of one long SameLine chain -- up to 16 candidates (Sampling's
        # Batch Candidates slider) never fit in one row at the Generate
        # panel's actual width, overflowing it horizontally.
        batch_button_size = 28.0
        item_spacing_x = imgui.GetStyleVar(ctx, imgui.StyleVar_ItemSpacing())[0]
        avail_w, _ = imgui.GetContentRegionAvail(ctx)
        per_row = max(1, int((avail_w + item_spacing_x) / (batch_button_size + item_spacing_x)))
        for i, cand in enumerate(candidates):
            if i > 0 and i % per_row != 0:
                imgui.SameLine(ctx)
            ok = cand.get("score") is not None
            if not ok:
                imgui.BeginDisabled(ctx)
            is_selected = selected == i
            if is_selected:
                imgui.PushStyleColor(ctx, imgui.Col_Button(), _signed32(0x992E2EFF))
            if imgui.Button(ctx, f"{i + 1}##batch{i}", 28, 28):
                clicked = f"batch_select_{i}"
            if is_selected:
                imgui.PopStyleColor(ctx, 1)
            if not ok:
                imgui.EndDisabled(ctx)
            if imgui.IsItemHovered(ctx):
                tip = f"seed {cand.get('seed')}"
                if cand.get("truncated"):
                    tip += "  (truncated -- hit context ceiling)"
                if not ok:
                    tip += f"\nFAILED: {cand.get('error')}"
                imgui.SetTooltip(ctx, tip)

    return clicked

# ---------------------------------------------------------------------------
# UI: Global Options
# ---------------------------------------------------------------------------

def _table_slider_width(label):
    """Item width that actually leaves room for `label` to render, computed
    from the current column's real available width -- SetNextItemWidth(-1)
    (fill everything up to the edge) was the bug that made every Global
    Options slider's label disappear: -1 hands the *entire* column to the
    widget, so the label -- which Dear ImGui draws immediately after the
    widget on the same line -- has zero space left and never appears at
    all. This reserves label_width + a small gap first, floored so even a
    label wider than the column still leaves the slider itself usable
    (the label may then clip at the column edge, which is a far smaller
    problem than being invisible everywhere)."""
    avail_w, _ = imgui.GetContentRegionAvail(ctx)
    label_w, _ = imgui.CalcTextSize(ctx, label)
    return max(60.0, avail_w - label_w - 8.0)

def _slider_grid(table_id, rows, params, columns=2):
    """Draws (label, key, kind, lo, hi[, fmt]) rows as SliderInt/SliderDouble
    widgets `columns` to a line in a table -- 2 columns halves the vertical
    space vs. one full-width slider per row, which is most of why the old
    single-column Global Options section ran off the bottom of the window.
    But 2 columns only works when the panel is wide enough for both a label
    and a usable slider to share half of it -- pass columns=1 for a row set
    with long labels (Sampling's "Anti-nucleus mask_p (0.0=Off)", e.g.)
    that would otherwise just get clipped no matter how the slider width is
    computed, since the label text alone doesn't fit in half the panel.
    Returns True if any value changed this frame."""
    changed = False
    if not imgui.BeginTable(ctx, table_id, columns):
        return False
    try:
        for i, row in enumerate(rows):
            label, key, kind, lo, hi = row[:5]
            fmt = row[5] if len(row) > 5 else "%.2f"
            if i % columns == 0:
                imgui.TableNextRow(ctx)
            imgui.TableNextColumn(ctx)
            imgui.SetNextItemWidth(ctx, _table_slider_width(label))
            if kind == "int":
                c, v = imgui.SliderInt(ctx, label, params[key], lo, hi)
            else:
                c, v = imgui.SliderDouble(ctx, label, params[key], lo, hi, fmt)
            if c:
                params[key] = v
                changed = True
    finally:
        imgui.EndTable(ctx)
    return changed

def draw_global_options(params):
    """Draws Global Options grouped into collapsible sections instead of one
    long always-expanded list. "Generation" (temperature/context/bars/
    tracks-per-step) is what actually gets touched every run, so it starts
    open; "Hard Limits"/"Sampling"/"Checks" are occasional/advanced tuning,
    so they start collapsed -- one click away, but not eating vertical
    space by default. Returns True if any value changed this frame (caller
    should persist)."""
    changed = False

    if imgui.CollapsingHeader(ctx, "Generation", None, imgui.TreeNodeFlags_DefaultOpen())[0]:
        # Bars Per Step's max tracks model_dim, which can shrink below a
        # previously-saved value -- clamp for display the same way the
        # single-column version did, without touching the saved value
        # unless the user actually moves this slider.
        #
        # Single column, not a 2-column table -- same reasoning as Hard
        # Limits/Sampling below: even these relatively short labels didn't
        # leave enough room per column at the Generate panel's actual
        # width, clipping them.
        bars_per_step_display = min(params["bars_per_step"], params["model_dim"])
        imgui.SetNextItemWidth(ctx, _table_slider_width("Temperature"))
        c, v = imgui.SliderDouble(ctx, "Temperature", params["temperature"], 0.1, 3.0, "%.2f")
        if c: params["temperature"] = v; changed = True
        imgui.SetNextItemWidth(ctx, _table_slider_width("Context Size (Bars)"))
        c, v = imgui.SliderInt(ctx, "Context Size (Bars)", params["model_dim"], 2, 16)
        if c: params["model_dim"] = v; changed = True
        imgui.SetNextItemWidth(ctx, _table_slider_width("Bars Per Step"))
        c, v = imgui.SliderInt(ctx, "Bars Per Step", bars_per_step_display, 1, params["model_dim"])
        if c: params["bars_per_step"] = v; changed = True
        imgui.SetNextItemWidth(ctx, _table_slider_width("Tracks Per Step"))
        c, v = imgui.SliderInt(ctx, "Tracks Per Step", params["tracks_per_step"], 1, 16)
        if c: params["tracks_per_step"] = v; changed = True

    if imgui.CollapsingHeader(ctx, "Hard Limits")[0]:
        limit_rows = [
            ("Polyphony Hard Limit (0=Off)", "polyphony_hard_limit", "int", 0, 32),
            ("Density Hard Limit (0=Off)", "density_hard_limit", "int", 0, 64),
        ]
        # Single column -- these labels are long enough that 2 columns left
        # them clipped no matter how the slider width was computed (see
        # _slider_grid's docstring).
        if _slider_grid("##limits_grid", limit_rows, params, columns=1):
            changed = True

    if imgui.CollapsingHeader(ctx, "Sampling")[0]:
        sampling_rows = [
            ("Max Attempts", "max_attempts", "int", 1, 10),
            ("Temp Escalation (1.0=Off)", "temp_escalation", "double", 1.0, 3.0),
            ("Top-p (1.0=Off)", "top_p", "double", 0.0, 1.0),
            ("Top-k (0=Off)", "top_k", "int", 0, 500),
            ("Anti-nucleus mask_p (0.0=Off)", "mask_p", "double", 0.0, 0.95),
            ("Anti-nucleus mask_k (0=Off)", "mask_k", "int", 0, 100),
            ("Random Seed (-1=Random)", "seed", "int", -1, 999999),
            ("Batch Candidates", "num_candidates", "int", 1, 16),
        ]
        # Single column -- same reasoning as Hard Limits above; several of
        # these labels are the longest in the whole panel.
        if _slider_grid("##sampling_grid", sampling_rows, params, columns=1):
            changed = True
        if params.get("num_candidates", 1) > 1:
            imgui.TextDisabled(ctx, "Token streaming is unavailable above 1 candidate -- each run waits for all of them.")

    if imgui.CollapsingHeader(ctx, "Checks")[0]:
        # Stacked vertically, not SameLine-chained -- four radio buttons in
        # one row overflowed the Generate panel's actual width, forcing it
        # to scroll horizontally to see the rest.
        checks_idx = params["checks_idx"]
        for i, label in enumerate(CHECKS_LABELS):
            c, checks_idx = imgui.RadioButtonEx(ctx, label, checks_idx, i)
            if c:
                params["checks_idx"] = checks_idx
                changed = True

        c, v = imgui.Checkbox(ctx, "Shuffle Steps", bool(params["shuffle"]))
        if c: params["shuffle"] = int(v); changed = True

    return changed

# ---------------------------------------------------------------------------
# UI: Per-Track Controls
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Strip-widget helpers -- label on its own line above a hidden-label,
# full-width widget below it, rather than Dear ImGui's normal "widget, then
# label on the same line". Left over from when this was a ~220px-wide
# mixer channel strip (too narrow for a same-line label), but works fine
# indented under a CollapsingHeader too, and TextWrapped still matters for
# labels like "Pitch Class Set Size (0=Any)" if the window itself is
# narrow. Change to a same-line label if this ever stops needing to
# tolerate a narrow width at all.
# ---------------------------------------------------------------------------

def _strip_slider_int(label, value, lo, hi, id_suffix):
    imgui.TextWrapped(ctx, label)
    imgui.SetNextItemWidth(ctx, -1)
    return imgui.SliderInt(ctx, f"##{id_suffix}", value, lo, hi)

def _strip_slider_double(label, value, lo, hi, id_suffix, fmt="%.2f"):
    imgui.TextWrapped(ctx, label)
    imgui.SetNextItemWidth(ctx, -1)
    return imgui.SliderDouble(ctx, f"##{id_suffix}", value, lo, hi, fmt)

def _strip_combo(label, idx, items, id_suffix):
    imgui.TextWrapped(ctx, label)
    imgui.SetNextItemWidth(ctx, -1)
    return imgui.Combo(ctx, f"##{id_suffix}", idx, "\0".join(items) + "\0")

def _draw_pitch_remix_controls(p):
    """Pitch mask and remix (variation) controls for one track. Gated
    per-control by server_capabilities, since they depend on the loaded
    checkpoint's encoder config (see GET /info). Mutates p in place;
    returns True if anything changed this frame."""
    changed = False

    if server_capabilities.get("supports_pitch_mask"):
        imgui.SeparatorText(ctx, "Pitch Mask")

        c, v = _strip_combo("Pitch Mask Mode", p["pitch_mask_mode"], ["Off", "Scale", "Pitch Classes"], "pmmode")
        if c: p["pitch_mask_mode"] = v; changed = True

        if p["pitch_mask_mode"] == 1:
            c, v = _strip_combo("Root", p["pitch_mask_root"], NOTE_NAMES, "pmroot")
            if c: p["pitch_mask_root"] = v; changed = True

            scale_idx = server_scale_presets.index(p["pitch_mask_scale"]) if p["pitch_mask_scale"] in server_scale_presets else 0
            c, scale_idx = _strip_combo("Scale", scale_idx, server_scale_presets, "pmscale")
            if c: p["pitch_mask_scale"] = server_scale_presets[scale_idx]; changed = True

        elif p["pitch_mask_mode"] == 2:
            imgui.TextWrapped(ctx, "Allowed pitch classes:")
            # 3 per row (not all 12 on one SameLine chain like the old
            # full-width layout) -- 12 checkboxes-with-labels don't fit
            # across a ~260px strip.
            for row_start in range(0, 12, 3):
                for pcls in range(row_start, min(row_start + 3, 12)):
                    bit = 1 << pcls
                    checked = bool(p["pitch_mask_classes"] & bit)
                    c, v = imgui.Checkbox(ctx, f"{NOTE_NAMES[pcls]}##pc{pcls}", checked)
                    if c:
                        p["pitch_mask_classes"] = (p["pitch_mask_classes"] | bit) if v else (p["pitch_mask_classes"] & ~bit)
                        changed = True
                    if pcls < row_start + 2:
                        imgui.SameLine(ctx)

        if p["pitch_mask_mode"] != 0:
            c, v = _strip_combo("Soft Shape", p["pitch_shape_mode"], ["Off", "Uniform Register", "Normal Register"], "pshape")
            if c: p["pitch_shape_mode"] = v; changed = True

            if p["pitch_shape_mode"] == 1:
                c, v = _strip_slider_int("Shape Min Pitch", p["pitch_shape_min"], 0, 127, "shmin")
                if c: p["pitch_shape_min"] = v; changed = True
                c, v = _strip_slider_int("Shape Max Pitch", p["pitch_shape_max"], 0, 127, "shmax")
                if c: p["pitch_shape_max"] = v; changed = True
            elif p["pitch_shape_mode"] == 2:
                c, v = _strip_slider_int("Shape Mean Pitch", p["pitch_shape_mean"], 0, 127, "shmean")
                if c: p["pitch_shape_mean"] = v; changed = True
                c, v = _strip_slider_double("Shape Std Dev", p["pitch_shape_std"], 0.5, 40.0, "shstd", "%.1f")
                if c: p["pitch_shape_std"] = v; changed = True

    if server_capabilities.get("supports_remix"):
        imgui.SeparatorText(ctx, "Variation (Remix)")
        c, v = imgui.Checkbox(ctx, "Remix This Track's Bars##remixon", bool(p["remix_enabled"]))
        if c: p["remix_enabled"] = int(v); changed = True

        if p["remix_enabled"]:
            imgui.TextWrapped(ctx, "Regenerates the bars already here as a variation. Ignore/AR still decide which bars.")
            c, v = _strip_slider_double("Remix Amount", p["remix_amount"], 0.0, 1.0, "remixamt")
            if c: p["remix_amount"] = v; changed = True
            c, v = _strip_combo("Remix Mode", p["remix_mode"], ["Pitch Only", "Pitch + Duration"], "remixmode")
            if c: p["remix_mode"] = v; changed = True

    return changed

def _draw_track_strip_body(p, is_drum):
    """Draws one track's full parameter set, stacked vertically top to
    bottom within its strip (label above, hidden-label full-width widget
    below -- see the strip-widget helpers above). Same fields and
    drum/melodic/model_type gating as before, just laid out narrow-and-tall
    instead of wide-and-collapsed. Mutates p in place; returns True if
    anything changed this frame."""
    changed = False

    c, v = imgui.Checkbox(ctx, "Ignore##ign", bool(p["ignore"]))
    if c: p["ignore"] = int(v); changed = True
    c, v = imgui.Checkbox(ctx, "Autoregressive##ar", bool(p["autoregressive"]))
    if c: p["autoregressive"] = int(v); changed = True

    if is_drum is None:
        imgui.TextWrapped(ctx, "Instrument not detected -- showing all controls. Density=drum only, rest=melodic only.")

    if is_drum is not False:
        c, v = _strip_slider_int("Density (0=Any)", p["density"], 0, 10, "dens")
        if c: p["density"] = v; changed = True

    if is_drum is not True:
        c, v = _strip_slider_int("Polyphony Min (0=Any)", p["min_polyphony_q"], 0, 10, "pmin")
        if c: p["min_polyphony_q"] = v; changed = True

        c, v = _strip_slider_int("Polyphony Max (0=Any)", p["max_polyphony_q"], 0, 10, "pmax")
        if c: p["max_polyphony_q"] = v; changed = True

        c, v = _strip_combo("Note Duration Min", p["min_note_duration_q"], NOTE_DURATION_LABELS, "ndmin")
        if c: p["min_note_duration_q"] = v; changed = True

        c, v = _strip_combo("Note Duration Max", p["max_note_duration_q"], NOTE_DURATION_LABELS, "ndmax")
        if c: p["max_note_duration_q"] = v; changed = True

    if model_type in ("prism", "expressive"):
        if is_drum is not True:
            c, v = _strip_combo("Key Signature", p["key_signature"], KEY_SIGNATURE_LABELS, "key")
            if c: p["key_signature"] = v; changed = True

            c, v = _strip_slider_int("Pitch Range (0=Any)", p["pitch_range"], 0, 128, "prange")
            if c: p["pitch_range"] = v; changed = True

        c, v = _strip_slider_int("Silence Proportion (0=Any)", p["silence_proportion"], 0, 10, "sil")
        if c: p["silence_proportion"] = v; changed = True

        if is_drum is not True:
            c, v = _strip_slider_int("Pitch Class Set Size (0=Any)", p["pitch_class_set"], 0, 13, "pcset")
            if c: p["pitch_class_set"] = v; changed = True

    if model_type == "expressive":
        c, v = _strip_combo("Quantization Grid Depth (NOMML)", p["nomml"], NOMML_LABELS, "nomml")
        if c: p["nomml"] = v; changed = True

    if _draw_pitch_remix_controls(p):
        changed = True

    return changed

def draw_track_controls(track_params):
    """Draws one collapsible section per project track, stacked vertically
    -- a plain CollapsingHeader per track, full per-track controls
    (density/polyphony/Ignore/Autoregressive/etc, from
    _draw_track_strip_body) indented below when expanded. Returns True if
    any per-track value was edited this frame (caller should persist).

    Replaces an earlier horizontally-scrolling mixer-style layout (each
    track its own fixed-width column) that went through several rounds of
    both crashes -- a sibling child window per strip, then a scrolling
    table, each corrupted this ReaImGui build's window stack in a
    different way -- and layout bugs neither ever fully resolved. A plain
    vertical list of collapsible sections needs none of that: it draws
    straight into the caller's own "##tracks_panel" child (see loop()) --
    that child is already scrollable on its own, so a second, separately-
    scrollable child wrapped around this same content (an earlier version
    of this function had one, "##tracks_list") bought nothing and was
    exactly the kind of nested-scrolling-child arrangement that corrupts
    this ReaImGui build's window stack once a real scrollbar drag hits it.

    model_type (which per-track fields apply -- see _draw_track_strip_body)
    comes entirely from Setup's checkpoint picker via refresh_model_type();
    there's no override here, since a checkpoint only ever resolves to one
    of the architectures this dashboard already knows how to draw controls
    for."""
    changed = False

    num_tracks = RPR_CountTracks(0)
    if num_tracks == 0:
        imgui.TextDisabled(ctx, "No tracks in this project yet.")
        return changed

    imgui.Spacing(ctx)
    for i in range(num_tracks):
        track = RPR_GetTrack(0, i)
        guid = get_track_guid(track)
        name = RPR_GetSetMediaTrackInfo_String(track, "P_NAME", "", False)[3] or f"Track {i + 1}"

        p = dict(DEFAULT_TRACK_PARAMS)
        p.update(track_params.get(guid, {}))

        # Density only ever affects drum tracks, and Polyphony/Note
        # Duration/Key Signature/Pitch Range/Pitch Class Set only ever
        # affect melodic tracks -- infill.py's _compute_track_prompt_fields
        # silently drops whichever half doesn't apply. The track name is
        # ground truth for instrument identity (Setup Tracks' MIDI-content
        # detection only exists to auto-assign that name once); only fall
        # back to MIDI-content detection for a track that hasn't been
        # named/resolved yet. None (neither resolves) shows both rather
        # than guessing wrong.
        instrument = setup_tracks.GM_NAME_TO_INSTRUMENT.get(name.strip())
        if instrument is None:
            instrument = setup_tracks.detect_track_instrument(track)
        is_drum = (instrument == 128) if instrument is not None else None

        # Combine the loop index with guid (not guid alone) -- a brand
        # new track added this same session can transiently report an
        # empty/not-yet-assigned GUID. A CollapsingHeader colliding
        # with another on the same ID just means the two share
        # open/closed state (a UI glitch), not the child-window-map
        # corruption a mixer-strip design risked -- but there's no
        # reason to reintroduce even that.
        imgui.PushID(ctx, f"track_{i}_{guid}")
        try:
            imgui.SetNextItemOpen(ctx, not p["collapsed"])
            # Status shown right on the header instead of right-aligned
            # checkboxes -- those duplicated what _draw_track_strip_body
            # already draws when expanded, and computing their right-
            # aligned position (checkbox square + label + inter-
            # checkbox spacing) kept coming out a little wrong,
            # overflowing the row and forcing a small horizontal
            # scrollbar on the whole tracks list. Ignore takes priority
            # over Autoregressive when both happen to be set, matching
            # infill.py's own precedence between the two.
            #
            # "###hdr" (three #, not two) -- this label's VISIBLE part
            # changes with p["ignore"]/p["autoregressive"], but ### make
            # everything after it (not the usual ##) the *only* thing
            # hashed into this header's ID, so toggling those never
            # changes its identity out from under SetNextItemOpen above.
            if p["ignore"]:
                header_label = f"{i + 1}. {name}  [Ignored]"
                header_color = THEME_TEXT_MUTED
            elif p["autoregressive"]:
                header_label = f"{i + 1}. {name}  [Autoregressive]"
                header_color = THEME_ACCENT_BRIGHT
            else:
                header_label = f"{i + 1}. {name}"
                header_color = None

            if header_color is not None:
                imgui.PushStyleColor(ctx, imgui.Col_Text(), _signed32(header_color))
            try:
                is_expanded = imgui.CollapsingHeader(ctx, f"{header_label}###hdr")[0]
            finally:
                if header_color is not None:
                    imgui.PopStyleColor(ctx, 1)
            if is_expanded == p["collapsed"]:
                p["collapsed"] = int(not is_expanded)
                track_params[guid] = p
                changed = True

            if is_expanded:
                imgui.Indent(ctx)
                try:
                    if _draw_track_strip_body(p, is_drum):
                        track_params[guid] = p
                        changed = True
                finally:
                    imgui.Unindent(ctx)
        finally:
            imgui.PopID(ctx)

    return changed

# ---------------------------------------------------------------------------
# UI: Banner + Console log
# ---------------------------------------------------------------------------

def draw_banner(width, row_h):
    """Draws the centered MIDI-GPT wordmark in a fixed-size child -- shown
    next to Setup (see loop()). A fixed child (rather than the old full-
    window-width centering) so it can share its row with Setup's controls
    without either one caring about the other's actual content width."""
    imgui.PushFont(ctx, mono_font, MGPT_BANNER_FONT_SIZE)
    banner_w, banner_h = imgui.CalcTextSize(ctx, MGPT_BANNER)
    imgui.PopFont(ctx)

    imgui.BeginChild(ctx, "##banner", width, row_h)
    try:
        imgui.SetCursorPos(ctx, max(0.0, (width - banner_w) / 2),
                            max(0.0, (row_h - banner_h) / 2))
        imgui.PushFont(ctx, mono_font, MGPT_BANNER_FONT_SIZE)
        try:
            imgui.TextColored(ctx, _signed32(THEME_ACCENT), MGPT_BANNER)
        finally:
            imgui.PopFont(ctx)
    finally:
        imgui.EndChild(ctx)

def draw_console(row_h):
    # Read-only multiline input instead of plain Text -- lets the user
    # click-drag to select and Cmd/Ctrl+C to copy console output (e.g. to
    # paste an error message elsewhere), which Text doesn't support.
    avail_w, _ = imgui.GetContentRegionAvail(ctx)
    imgui.InputTextMultiline(
        ctx, "##console", "\n".join(log_lines), avail_w, row_h,
        imgui.InputTextFlags_ReadOnly())

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def init():
    global ctx, mono_font, params, track_params
    ctx = imgui.CreateContext('MIDI-GPT Dashboard')
    # "monospace" (the generic family) doesn't guarantee full, correctly-
    # sized glyphs for box-drawing/block characters (the banner/logo art
    # uses U+2550-259F) -- when a glyph is missing, ImGui/FreeType silently
    # substitutes a fallback font for just that character, which usually
    # has a different advance width, throwing off the ASCII-art grid line
    # by line (rows drift relative to each other depending on how many
    # block characters vs. plain text each line has). Menlo is macOS's
    # terminal font and has full, correctly-metriced box-drawing coverage.
    mono_font = imgui.CreateFont('Menlo')
    imgui.Attach(ctx, mono_font)
    params = load_global_params()
    track_params = load_track_params()
    refresh_model_type()
    loop()

def push_theme():
    """Dark-red theme, pushed around the whole window (including Begin())
    so it covers the titlebar too, not just the content. Every value here
    is one of the named THEME_* constants at the top of the file -- that's
    the single place to edit to retheme the dashboard, including the ad hoc
    TextColored() calls elsewhere that reference the same constants."""
    theme = [
        (imgui.Col_WindowBg(),             THEME_BG),
        (imgui.Col_ChildBg(),              THEME_BG_CHILD),
        (imgui.Col_PopupBg(),              THEME_BG),
        (imgui.Col_TitleBg(),              THEME_BG_TITLE),
        (imgui.Col_TitleBgActive(),        THEME_BG_TITLE_ACTIVE),
        (imgui.Col_Header(),               THEME_BG_SURFACE),
        (imgui.Col_HeaderHovered(),        THEME_ACCENT_DIM),
        (imgui.Col_HeaderActive(),         THEME_ACCENT_HOVER),
        (imgui.Col_Button(),               THEME_ACCENT_DIM),
        (imgui.Col_ButtonHovered(),        THEME_ACCENT_HOVER),
        (imgui.Col_ButtonActive(),         THEME_ACCENT_ACTIVE),
        (imgui.Col_FrameBg(),              THEME_BG_FRAME),
        (imgui.Col_FrameBgHovered(),       THEME_BG_FRAME_HOVER),
        (imgui.Col_FrameBgActive(),        THEME_BG_FRAME_ACTIVE),
        (imgui.Col_CheckMark(),            THEME_ACCENT),
        (imgui.Col_SliderGrab(),           THEME_ACCENT_DEEP),
        (imgui.Col_SliderGrabActive(),     THEME_ACCENT_BRIGHT),
        (imgui.Col_Border(),               THEME_ACCENT_DIM),
        (imgui.Col_Separator(),            THEME_ACCENT_DIM),
        (imgui.Col_SeparatorHovered(),     THEME_ACCENT_ACTIVE),
        (imgui.Col_SeparatorActive(),      THEME_ACCENT_BRIGHT),
        (imgui.Col_Text(),                 THEME_TEXT),
        (imgui.Col_ScrollbarBg(),          THEME_BG),
        (imgui.Col_ScrollbarGrab(),        THEME_ACCENT_DIM),
        (imgui.Col_ScrollbarGrabHovered(), THEME_ACCENT_HOVER),
        (imgui.Col_ScrollbarGrabActive(),  THEME_ACCENT_ACTIVE),
    ]
    for col, rgba in theme:
        imgui.PushStyleColor(ctx, col, _signed32(rgba))
    return len(theme)

def loop():
    global active_generation, active_batch, last_generation_result
    global measured_console_header_h, measured_window_chrome_h, last_window_w

    # Poll for a finished background generation *before* Begin() -- same
    # timing as the "after End()" side effects below (nothing has opened an
    # ImGui frame yet this cycle), so the write-back's REAPER API calls
    # can't corrupt an in-progress frame.
    if active_generation is not None:
        handle = active_generation["handle"]
        with handle.lock:
            done = handle.done
        if done:
            finished_ctx = active_generation["ctx"]
            active_generation = None
            try:
                result = infill.finish_generation(handle, finished_ctx)
            except Exception:
                # A bad server response shape or a stale REAPER object
                # reference here must not kill the defer loop -- that would
                # freeze the whole dashboard until it's manually reopened,
                # for what's usually just one bad generation. Log and move
                # on; active_generation is already cleared above so the
                # next "Run Infill" isn't blocked.
                import traceback
                print(traceback.format_exc() + "\n")
                result = None
            if result is not None:
                last_generation_result = result
                if result.get("candidates") is not None:
                    active_batch = {
                        "candidates": result["candidates"],
                        "selected": result.get("selected_index"),
                        "ctx": finished_ctx,
                    }
                else:
                    active_batch = None

    theme_count = push_theme()

    clicked = None
    error_tb = None
    need_save_global = False
    need_save_track = False
    is_open = True

    try:
        # 1150x700, not the old 560x1050 -- 1050px tall opened taller than
        # most laptop screens' usable height on first-ever launch, and
        # since ReaImGui persists geometry after that, the resize handle
        # needed to shrink it back down could end up off-screen with
        # nothing to grab. Wider instead of taller fits this layout better
        # anyway: Generate and the Tracks mixer sit side by side (see the
        # main_content block below), so there's more width to fill and
        # less height needed than one long stacked column ever had.
        imgui.SetNextWindowSize(ctx, 1150, 700, imgui.Cond_FirstUseEver())
        # This ReaImGui build persists window geometry across script runs,
        # and Cond_FirstUseEver never re-applies once that saved state
        # exists. If the window is ever dragged down to (near) zero height,
        # every future launch reloads that degenerate geometry and crashes
        # on Begin() before we get a chance to draw anything -- so resizing
        # is clamped to a sane minimum every frame (not just once), since a
        # one-time reset can't undo a state that's re-saved degenerate on
        # every crash. Collapsing is left enabled; visible=False already
        # skips drawing safely below.
        #
        # setup_row_h is exact -- it's the height WE give "##setup_body"
        # (see below), so it's whatever SETUP_ROW_COUNT widget rows plus
        # that child's own top/bottom WindowPadding actually costs, not a
        # guess. console_header_h and window_chrome_h are each the REAL
        # measured value from the previous frame (see
        # measured_console_header_h / measured_window_chrome_h's own
        # comments above) -- not formulas. Only the very first frame
        # (before any measurement exists) falls back to a formula/constant
        # guess, since being wrong for exactly one frame is harmless.
        setup_row_h = (imgui.GetFrameHeightWithSpacing(ctx) * SETUP_ROW_COUNT
                        + imgui.GetStyleVar(ctx, imgui.StyleVar_WindowPadding())[1] * 2)
        if measured_console_header_h is not None:
            console_header_h = measured_console_header_h
        else:
            console_header_h = imgui.GetTextLineHeightWithSpacing(ctx) * 2.0
        if measured_window_chrome_h is not None:
            window_chrome_h = measured_window_chrome_h
        else:
            window_chrome_h = WINDOW_CHROME_ESTIMATE

        # Mode decided from last frame's actual window width (see
        # last_window_w's comment) -- this frame's real width isn't known
        # until after Begin(), which is too late for a size constraint.
        # The width floor itself, though, must NOT depend on this mode: if
        # it did (700 while "wide", 380 once "narrow"), the 700 floor would
        # never let the window narrow past 700 in the first place, so
        # last_window_w could never drop below 700, so narrow_layout could
        # never become true -- a permanent deadlock. MIN_WINDOW_WIDTH is
        # therefore the unconditional floor in both modes; only min height
        # depends on which layout is currently active.
        narrow_layout = last_window_w is not None and last_window_w < NARROW_LAYOUT_WIDTH
        if narrow_layout:
            # Four rows stacked instead of two -- Generate and Tracks each
            # need their own CONTENT_MIN_HEIGHT floor now that they're not
            # sharing a row.
            min_window_h = (setup_row_h + CONTENT_MIN_HEIGHT * 2 + console_header_h
                             + CONSOLE_ROW_HEIGHT + window_chrome_h)
        else:
            min_window_h = (setup_row_h + CONTENT_MIN_HEIGHT + console_header_h
                             + CONSOLE_ROW_HEIGHT + window_chrome_h)
        max_window_h = min_window_h * HEIGHT_MAX_MULTIPLIER
        imgui.SetNextWindowSizeConstraints(ctx, MIN_WINDOW_WIDTH, min_window_h, 100000, max_window_h)
        # "##layout6" (invisible in the title bar -- everything after "##"
        # is ID-only, not displayed) gives this window a fresh identity with
        # no saved geometry, so the new SetNextWindowSize above actually
        # takes effect. Without it, Cond_FirstUseEver is a no-op for anyone
        # who already has ReaImGui-persisted geometry saved under an older
        # id from before this layout existed -- it only applies the very
        # first time a given window id is ever seen, not on every code
        # change. Bumped from ##layout5 -> ##layout6 alongside simplifying
        # the console back down to a fixed-height box (no collapsing, no
        # popout window), since the old layout's proportions no longer
        # apply. Bump again in the future if the default size/layout
        # changes enough to want to reset it once more.
        visible, is_open = imgui.Begin(ctx, "MIDI-GPT Dashboard##layout6", True)

        if visible:
            try:
                # Real chrome (title bar + top/bottom WindowPadding),
                # measured right after Begin() -- cached in
                # measured_window_chrome_h (see its own comment) for next
                # frame's min_window_h calculation above. Only measured
                # here (not when collapsed/invisible), since a collapsed
                # window's content region doesn't reflect real chrome.
                _, chrome_avail_h = imgui.GetContentRegionAvail(ctx)
                measured_window_chrome_h = imgui.GetWindowHeight(ctx) - chrome_avail_h

                # Cache the real width for next frame's pre-Begin decision
                # -- but keep drawing this frame with the SAME narrow_layout
                # already decided above, rather than re-deriving it from
                # this fresh value. Re-deriving it here used to let the two
                # disagree mid-drag (this frame's true width can differ
                # from the width min_window_h was just sized for), so for
                # exactly the transitional frame(s) the window would be
                # sized for one layout while content rendered for the
                # other -- an overflow that corrupted this ReaImGui
                # build's window stack ("Assertion failed:
                # child_window->Flags & ImGuiWindowFlags_ChildWindow") the
                # same way every other overflow has all session. One
                # frame of lag on which layout gets drawn during a resize
                # is a small price for that never happening again.
                last_window_w = imgui.GetWindowWidth(ctx)

                # Wide: Setup (rarely touched once configured) shares its
                # row with the MIDI-GPT wordmark, wordmark on the left,
                # then Generate (Run Infill + progress + Global Options --
                # what's touched every run) and Tracks sit side by side
                # below, both visible at once rather than switching between
                # them. Narrow: the same four sections stacked full-width,
                # one per row, since there's no longer room to put any two
                # of them side by side. No "Setup" label above it either
                # way -- the row's contents are self-explanatory.
                if narrow_layout:
                    avail_w0, _ = imgui.GetContentRegionAvail(ctx)
                    imgui.PushFont(ctx, mono_font, MGPT_BANNER_FONT_SIZE)
                    _, banner_text_h = imgui.CalcTextSize(ctx, MGPT_BANNER)
                    imgui.PopFont(ctx)
                    banner_row_h = (banner_text_h
                                     + imgui.GetStyleVar(ctx, imgui.StyleVar_WindowPadding())[1] * 2)
                    draw_banner(avail_w0, banner_row_h)
                else:
                    draw_banner(BANNER_CHILD_WIDTH, setup_row_h)
                    imgui.SameLine(ctx)

                imgui.BeginChild(ctx, "##setup_body", 0, setup_row_h)
                try:
                    setup_clicked = draw_setup_panel()
                    if setup_clicked:
                        clicked = setup_clicked
                finally:
                    imgui.EndChild(ctx)

                # No Spacing/Separator/Spacing here -- it wasn't buying
                # anything visually and just ate into the window's usable
                # height. avail_h here is a live measurement taken directly
                # in the window (no wrapping child in between), so it's
                # exactly what's really left after Setup -- no guessing
                # about Setup's own overhead needed to get this number.
                avail_w, avail_h = imgui.GetContentRegionAvail(ctx)

                # Console is a flat CONSOLE_ROW_HEIGHT (plus its own
                # SeparatorText row). Wide: Generate/Tracks share the rest
                # of the height, side by side, with no ceiling of their
                # own. Narrow: they split the rest between them instead,
                # stacked, each still floored at CONTENT_MIN_HEIGHT.
                stack_h = avail_h - CONSOLE_ROW_HEIGHT - console_header_h
                if narrow_layout:
                    generate_w = 0
                    generate_h = max(CONTENT_MIN_HEIGHT, stack_h / 2)
                    tracks_h = max(CONTENT_MIN_HEIGHT, stack_h - generate_h)
                else:
                    generate_w = min(GENERATE_PANEL_WIDTH, max(260.0, avail_w * 0.4))
                    generate_h = max(CONTENT_MIN_HEIGHT, stack_h)
                    tracks_h = generate_h

                imgui.BeginChild(ctx, "##generate_panel", generate_w, generate_h)
                try:
                    imgui.SeparatorText(ctx, "Generate")
                    if imgui.Button(ctx, "Run Infill", -1, 32):
                        clicked = "run_infill"
                    gen_clicked = draw_generation_result()
                    if gen_clicked:
                        clicked = gen_clicked
                    imgui.Spacing(ctx)
                    need_save_global = draw_global_options(params)
                finally:
                    imgui.EndChild(ctx)

                if not narrow_layout:
                    imgui.SameLine(ctx)
                imgui.BeginChild(ctx, "##tracks_panel", 0, tracks_h)
                try:
                    imgui.SeparatorText(ctx, "Tracks")
                    need_save_track = draw_track_controls(track_params)
                finally:
                    imgui.EndChild(ctx)

                # Real height measured via cursor position, not guessed --
                # cached in measured_console_header_h (see its own comment)
                # for next frame's content_h calculation above.
                cursor_y_before = imgui.GetCursorPosY(ctx)
                imgui.SeparatorText(ctx, "Console")
                measured_console_header_h = imgui.GetCursorPosY(ctx) - cursor_y_before
                draw_console(CONSOLE_ROW_HEIGHT)
            except Exception:
                # Defer printing until after End() -- keeps this path
                # consistent with the other post-frame side effects below
                # (saves, actions).
                import traceback
                error_tb = traceback.format_exc()
            finally:
                # In this ReaImGui build, End() must be called only when
                # Begin() returned visible=True -- calling it when visible
                # is False (e.g. window collapsed) throws "Calling End() too
                # many times!" since Begin() didn't push a window onto the
                # stack in that case. It must also always run even if
                # something above raised, or the frame is left open and the
                # next frame's calls desync.
                imgui.End(ctx)
    finally:
        imgui.PopStyleColor(ctx, theme_count)

    # Any REAPER API call with side effects (ExtState writes, console
    # messages, dialogs) must happen after End() closes the frame -- doing
    # it mid-frame is what was corrupting ReaImGui's window stack.
    if error_tb:
        print(error_tb + "\n")

    if need_save_global:
        save_global_params(params)

    if need_save_track:
        save_track_params(track_params)

    try:
        if clicked == "cancel_generation":
            if active_generation is not None:
                infill.cancel_generation(active_generation["handle"])
                print("Cancellation requested -- waiting for the server to stop...\n")
        elif clicked and clicked.startswith("batch_select_"):
            switch_batch_candidate(int(clicked[len("batch_select_"):]))
        elif clicked in ACTIONS:
            log_lines.clear()
            ACTIONS[clicked]()
    except Exception:
        # Same reasoning as the finish_generation() guard above -- an
        # action button (setup tracks, apply soundfont template, etc.)
        # throwing here must not kill the defer loop.
        import traceback
        print(traceback.format_exc() + "\n")

    if is_open:
        RPR_defer("loop()")
    elif active_generation is not None:
        # The window was closed with a generation still in flight. Nothing
        # else cancels it -- the background thread (REAPER_midigpt_infill.py)
        # would otherwise keep running against the server for up to its own
        # timeout with no cancel ever sent, and a server that only handles
        # one generation at a time would leave the *next* dashboard session's
        # first request stalled behind this orphaned one.
        infill.cancel_generation(active_generation["handle"])
        print("Dashboard closed with a generation in flight -- cancelling it.\n")

RPR_defer("init()")
