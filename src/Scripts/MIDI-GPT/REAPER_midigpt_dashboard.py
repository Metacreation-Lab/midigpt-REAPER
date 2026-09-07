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
import REAPER_midigpt_set_server as set_server
import REAPER_midigpt_set_soundfont_template as set_soundfont_template
import REAPER_midigpt_apply_soundfont_template as apply_soundfont_template

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
# Preferred height of the console+logo row when there's enough window
# height to go around, and the main content area's (Actions/Options/Track
# Controls) preferred minimum before the console starts giving up height.
# Both are just preferences, not guarantees -- see the sizing math in
# loop() for why they're never allowed to sum past what's available.
CONSOLE_ROW_HEIGHT = 200
MIN_CONTENT_HEIGHT = 250

# Width of one track's mixer-style channel strip in the Tracks panel -- wide
# enough for "Pitch Class Set Size (0=Any)"-length labels to wrap at most
# two lines, narrow enough that several tracks fit before the horizontal
# scrollbar kicks in.
TRACK_STRIP_WIDTH = 260.0

# Preferred width of the Generate panel (left column) -- mostly vertical
# sliders, so it doesn't need much width; the Tracks mixer to its right
# gets whatever's left, since that one actually wants it (see
# draw_track_controls). Falls back to 40% of the available width instead
# on a narrow window rather than leaving the mixer with no room at all.
GENERATE_PANEL_WIDTH = 380.0

# Fixed height of the Setup row (server/model/instrument-provisioning
# controls, logo to their left) -- needs an explicit height, not just
# "whatever its content needs", since draw_logo() has to know a row_h to
# center the logo art within. Sized generously enough that draw_setup_panel
# never needs its own internal scrollbar at typical window widths.
SETUP_ROW_HEIGHT = 190.0

TRACK_PARAMS_KEY = "track_params_v1"

DEFAULT_TRACK_PARAMS = {
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

MODEL_TYPES = ["yellow", "prism", "expressive"]
MODEL_LABELS = {"yellow": "Yellow", "prism": "Prism", "expressive": "Expressive"}

# MIDI-GPT wordmark banner across the top of the window. Fixed font size and
# height regardless of window size -- only its horizontal centering moves as
# the window is resized. Uses \uXXXX escapes (box-drawing characters aren't
# ASCII) for the same reason LOGO's comment below explains.
MGPT_BANNER = (
    "\u2588\u2588\u2588\u2557   \u2588\u2588\u2588\u2557      \u2588\u2588\u2588\u2588\u2588\u2588\u2557   \u2588\u2588\u2588\u2588\u2588\u2588\u2557   \u2588\u2588\u2588\u2588\u2588\u2557              \u2588\u2588\u2588\u2588\u2588\u2588\u2557   \u2588\u2588\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\n"
    "\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2551      \u2588\u2588\u2554\u2550\u2550\u2550\u255d   \u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557  \u255a\u2550\u2588\u2588\u2554\u255d             \u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255d   \u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557 \u255a\u2550\u2550\u2588\u2588\u2554\u2550\u2550\u255d\n"
    "\u2588\u2588\u2554\u2588\u2588\u2588\u2588\u2554\u2588\u2588\u2551      \u2588\u2588\u2551       \u2588\u2588\u2551  \u2588\u2588\u2551    \u2588\u2588\u2551    \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2551  \u2588\u2588\u2588\u2557  \u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d    \u2588\u2588\u2551   \n"
    "\u2588\u2588\u2551\u255a\u2588\u2588\u2554\u255d\u2588\u2588\u2551      \u2588\u2588\u2551       \u2588\u2588\u2551  \u2588\u2588\u2551    \u2588\u2588\u2551    \u255a\u2550\u2550\u2550\u2550\u2550\u2550\u255d  \u2588\u2588\u2551   \u2588\u2588\u2551  \u2588\u2588\u2554\u2550\u2550\u2550\u255d     \u2588\u2588\u2551   \n"
    "\u2588\u2588\u2551 \u255a\u2550\u255d \u2588\u2588\u2551  \u25e2\u2588\u2588\u2588\u2588\u2588\u2557       \u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d  \u2588\u2588\u2588\u2588\u2588\u2557             \u255a\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d  \u2588\u2588\u2551         \u2588\u2588\u2551   \n"
    "\u255a\u2550\u255d     \u255a\u2550\u255d  \u2588\u2588\u2588\u2588\u2588\u2588\u2551       \u255a\u2550\u2550\u2550\u2550\u2550\u255d   \u255a\u2550\u2550\u2550\u2550\u255d              \u255a\u2550\u2550\u2550\u2550\u2550\u255d   \u255a\u2550\u255d         \u255a\u2550\u255d   \n"
    "             \u255a\u2588\u2588\u2588\u2588\u2588\u2554\u255d"
)
MGPT_BANNER_FONT_SIZE = 7.5

# Metacreation Lab logo, shown next to the console. Pure ASCII (unlike the
# old banner's box-drawing characters) so it doesn't need \uXXXX escaping --
# REAPER's embedded Python interpreter reads script files as ASCII regardless
# of a "# -*- coding: utf-8 -*-" header, and raw non-ASCII bytes in the
# source crash with UnicodeDecodeError.
LOGO = (
    "                                                                             \n"
    "                           :==::.                                            \n"
    "                         :====%#+%=                                          \n"
    "                       :=+==%%*@@@#%=                                        \n"
    "                      -*++#%*@@@@@@@#%:                                      \n"
    "                        .:-=@@@@@@@@@@#%:                                    \n"
    "                           ::*@@@@@@@@@%%%.                                  \n"
    "                            .:-*@@@@@@@@@%%*.                                \n"
    "                              .:=#@@@@@@@@@%%+.                              \n"
    "                                .:=%@@@@@@@@@#%=                             \n"
    "                                  .-=%@@@@@@@@@*%:                           \n"
    "                        -+=:.       .-*@@@@@@@@@@#%.                         \n"
    "                      :++++#@-=:      :-*@@@@@@@@@%#%.                       \n"
    "                    :++++*@+#@@*=:      .:*@@@@@@@@@%%*.                     \n"
    "                  :++++*%**@@@@@%*=.      :-#@@@@@@@@@%%*.                   \n"
    "                :++++*@%*@@@@@@@@@%=.       :=%@@@@@@@@@%%=                  \n"
    "              .=+++*%%+@@@@@@@@@%+:           :=%@@@@@@@@@#%=                \n"
    "            .=++++%%*%@@@@@@@@%+-               :=%@@@@@@@@@#%:              \n"
    "          .=++++#@*%@@@@@@@@%+-                  .:+%@@@@@@@@%##:            \n"
    "        .-+*+*#@*%@@@@@@@@%*-.                     .:*%@@@@@@@@%**:          \n"
    "        .:+**@*#@@@@@@@@%*=.                      :::::*@@@@@@@@@%**.        \n"
    "            ::#@@@@@@@@@#=:                     :==:::#+*@@@@@@@@@#:.        \n"
    "             .:=%@@@@@@@@%#*-                 .=----*%*@@@@@@@@@%-.          \n"
    "               .:+%@@@@@@@@%**:             .-----*%*%@@@@@@@@%=:            \n"
    "                 .:+%@@@@@@@@%**:         .:--::+%*%@@@@@@@@%=:              \n"
    "                   .:*%@@@@@@@@%*+.     .:--::=@*%@@@@@@@@%+:                \n"
    "                     .:*@@@@@@@@@%*=   :-:::=@*%@@@@@@@@@*:                  \n"
    "                       .-*@@@@@@@%=: :-:::-%##@@@@@@@@@*:.                   \n"
    "                         .-#@@@%+:.:::::-##*%@@@@@@@@#-.                     \n"
    "                          ..=%*: .:.  :+%+%@@@@@@@@%=.                       \n"
    "                            .:..-.  .-#=%@@@@@@@@%=.                         \n"
    "                              =:...:#=%@@@@@@@@@=:                           \n"
    "                            ====::#+#@@@@@@@@@+:                             \n"
    "                          -++++*@**@@@@@@@@@*:.                              \n"
    "                        -++++*%#*%@@@@@@@@*:.                                \n"
    "                      :*+++*%%*%@@@@@@@@#:.                                  \n"
    "                       :=*%@+%@@@@@@@@%:.                                    \n"
    "                         .:-%@@@@@@%%=.                                      \n"
    "                           .:+%@@%%=:                                        \n"
    "                             .:*%+:                                          \n"
    "                               ..                                            \n"
)
LOGO_FONT_SIZE = 2.8
LOGO_CHILD_WIDTH = 160.0
LOGO_COLOR = 0xE63946FF

# ---------------------------------------------------------------------------
# Console: writes only to the in-window scrolling log, not REAPER's native
# console, since this dashboard has its own dedicated console area -- no
# need to alt-tab out to see what happened. Set *after* importing the
# action modules above (each of which sets its own sys.stdout at import
# time) so this one wins for everything printed from here on, regardless
# of which module's function is actually running.
# ---------------------------------------------------------------------------

log_lines = []

class _DashboardConsole:
    def __init__(self):
        self._buf = ""
    def write(self, s):
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            log_lines.append(line)
        del log_lines[:-MAX_LOG_LINES]
    def flush(self):
        pass

sys.stdout = sys.stderr = _DashboardConsole()

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

def set_server_and_refresh():
    """Runs the 'Set server' dialog, then immediately re-detects the model
    type/capabilities/list against whatever server the user just pointed at
    -- otherwise the model picker keeps showing the old server's data until
    the user notices and clicks 'Refresh##model' themselves."""
    set_server.run_set_server()
    refresh_model_type()

ACTIONS = {
    "set_server":              set_server_and_refresh,
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

    global selected_model

    server_url = infill.get_server_url()
    imgui.Text(ctx, f"Server: {server_url}")
    imgui.SameLine(ctx)
    if imgui.Button(ctx, "Change...##server"):
        clicked = "set_server"

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

    imgui.Spacing(ctx)
    imgui.SeparatorText(ctx, "Tracks && Instruments")

    if imgui.Button(ctx, "Setup Tracks"):
        clicked = "setup_tracks"

    imgui.SameLine(ctx)
    if imgui.Button(ctx, "Use Selected Track as SoundFont Template"):
        clicked = "set_soundfont_template"

    imgui.SameLine(ctx)
    if imgui.Button(ctx, "Apply Template to Selected Tracks"):
        clicked = "apply_soundfont_template"

    imgui.Spacing(ctx)
    imgui.SeparatorText(ctx, "Reset")

    if imgui.Button(ctx, "Reset Global Options && Track Controls"):
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
        imgui.TextColored(ctx, _signed32(0xFFAA33FF), f"    [{status}]")

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
        imgui.TextColored(ctx, _signed32(0xFF6666FF),
                           "Truncated -- hit the context ceiling before finishing (may be cut off mid-bar)")

    clicked = None
    candidates = last_generation_result.get("candidates")
    if candidates:
        imgui.SeparatorText(ctx, "Batch Candidates")
        imgui.TextDisabled(ctx, "Swap freely and listen -- the next generation makes your pick permanent.")
        selected = active_batch.get("selected") if active_batch else last_generation_result.get("selected_index")
        for i, cand in enumerate(candidates):
            if i > 0:
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

def _slider_grid(table_id, rows, params):
    """Draws (label, key, kind, lo, hi[, fmt]) rows as SliderInt/SliderDouble
    widgets two to a line in a table -- halves the vertical space vs. one
    full-width slider per row, which is most of why the old single-column
    Global Options section ran off the bottom of the window. Returns True
    if any value changed this frame."""
    changed = False
    if not imgui.BeginTable(ctx, table_id, 2):
        return False
    try:
        for i, row in enumerate(rows):
            label, key, kind, lo, hi = row[:5]
            fmt = row[5] if len(row) > 5 else "%.2f"
            if i % 2 == 0:
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
        bars_per_step_display = min(params["bars_per_step"], params["model_dim"])
        if imgui.BeginTable(ctx, "##gen_grid", 2):
            try:
                imgui.TableNextRow(ctx)
                imgui.TableNextColumn(ctx)
                imgui.SetNextItemWidth(ctx, _table_slider_width("Temperature"))
                c, v = imgui.SliderDouble(ctx, "Temperature", params["temperature"], 0.1, 3.0, "%.2f")
                if c: params["temperature"] = v; changed = True
                imgui.TableNextColumn(ctx)
                imgui.SetNextItemWidth(ctx, _table_slider_width("Context Size (Bars)"))
                c, v = imgui.SliderInt(ctx, "Context Size (Bars)", params["model_dim"], 2, 16)
                if c: params["model_dim"] = v; changed = True

                imgui.TableNextRow(ctx)
                imgui.TableNextColumn(ctx)
                imgui.SetNextItemWidth(ctx, _table_slider_width("Bars Per Step"))
                c, v = imgui.SliderInt(ctx, "Bars Per Step", bars_per_step_display, 1, params["model_dim"])
                if c: params["bars_per_step"] = v; changed = True
                imgui.TableNextColumn(ctx)
                imgui.SetNextItemWidth(ctx, _table_slider_width("Tracks Per Step"))
                c, v = imgui.SliderInt(ctx, "Tracks Per Step", params["tracks_per_step"], 1, 16)
                if c: params["tracks_per_step"] = v; changed = True
            finally:
                imgui.EndTable(ctx)

    if imgui.CollapsingHeader(ctx, "Hard Limits")[0]:
        limit_rows = [
            ("Polyphony Hard Limit (0=Off)", "polyphony_hard_limit", "int", 0, 32),
            ("Density Hard Limit (0=Off)", "density_hard_limit", "int", 0, 64),
        ]
        if _slider_grid("##limits_grid", limit_rows, params):
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
            ("Batch Candidates (num_candidates)", "num_candidates", "int", 1, 16),
        ]
        if _slider_grid("##sampling_grid", sampling_rows, params):
            changed = True
        if params.get("num_candidates", 1) > 1:
            imgui.TextDisabled(ctx, "Token streaming is unavailable above 1 candidate -- each run waits for all of them.")

    if imgui.CollapsingHeader(ctx, "Checks")[0]:
        checks_idx = params["checks_idx"]
        for i, label in enumerate(CHECKS_LABELS):
            c, checks_idx = imgui.RadioButtonEx(ctx, label, checks_idx, i)
            if c:
                params["checks_idx"] = checks_idx
                changed = True
            if i < len(CHECKS_LABELS) - 1:
                imgui.SameLine(ctx)

        c, v = imgui.Checkbox(ctx, "Shuffle Steps", bool(params["shuffle"]))
        if c: params["shuffle"] = int(v); changed = True

    return changed

# ---------------------------------------------------------------------------
# UI: Per-Track Controls
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Strip-widget helpers -- a mixer channel strip is only ~TRACK_STRIP_WIDTH
# px wide, too narrow for Dear ImGui's normal "widget, then label on the
# same line" layout (there's no room left for the label once the widget
# fills the width). Every strip control instead draws its label on its own
# line above a hidden-label, full-width widget below it. TextWrapped (not
# Text) for labels since some ("Pitch Class Set Size (0=Any)") are longer
# than the strip is wide.
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
    """Draws the Model selector, then a horizontally-scrolling mixer-style
    strip per project track -- like a DAW mixer, each track is a narrow,
    bordered, independently-vertically-scrolling column instead of a
    full-width CollapsingHeader. N tracks grow the layout sideways
    (scrollable) instead of each one eating unbounded vertical height on
    top of the others. Returns (changed, clicked) -- changed is True if any
    per-track value was edited this frame (caller should persist); clicked
    is set to "refresh_model" if the Refresh button was pressed (run after
    End(), same rule as draw_setup_panel())."""
    global model_type
    changed = False
    clicked = None

    imgui.Text(ctx, f"Model: {MODEL_LABELS.get(model_type, model_type)}")
    imgui.SameLine(ctx)
    if imgui.Button(ctx, "Refresh##model"):
        clicked = "refresh_model"
    imgui.SameLine(ctx)
    imgui.SetNextItemWidth(ctx, 140)
    idx = MODEL_TYPES.index(model_type) if model_type in MODEL_TYPES else 0
    c, idx = imgui.Combo(ctx, "##model_override", idx, "\0".join(MODEL_LABELS[m] for m in MODEL_TYPES) + "\0")
    if c:
        model_type = MODEL_TYPES[idx]

    num_tracks = RPR_CountTracks(0)
    if num_tracks == 0:
        imgui.TextDisabled(ctx, "No tracks in this project yet.")
        return changed, clicked

    imgui.Spacing(ctx)
    _, avail_h = imgui.GetContentRegionAvail(ctx)
    imgui.BeginChild(ctx, "##track_mixer", 0, max(1.0, avail_h), None, imgui.WindowFlags_HorizontalScrollbar())
    try:
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

            if i > 0:
                imgui.SameLine(ctx)

            # Combine the loop index with guid (not guid alone) -- a brand
            # new track added this same session can transiently report an
            # empty/not-yet-assigned GUID, and unlike the old
            # CollapsingHeader (where a duplicate ID just meant two headers
            # shared open/closed state -- a UI glitch), BeginChild registers
            # an actual child *window* keyed by this ID: two strips
            # colliding on it corrupts ReaImGui's internal window map,
            # which is what "!ImGui_EndChild: Missing PopID()" followed by
            # every subsequent call reporting an invalid context actually
            # was. PushID/PopID both now live inside their own try/finally
            # too, so an exception drawing one strip's contents can never
            # leave the ID stack unbalanced for every frame after it.
            imgui.PushID(ctx, f"track_{i}_{guid}")
            try:
                imgui.BeginChild(ctx, "##strip", TRACK_STRIP_WIDTH, 0, imgui.ChildFlags_Borders())
                try:
                    imgui.TextWrapped(ctx, f"{i + 1}. {name}")
                    if p["ignore"]:
                        imgui.TextColored(ctx, _signed32(0xFFAA33FF), "Ignored")
                    elif p["autoregressive"]:
                        imgui.TextColored(ctx, _signed32(0x66CCFFFF), "Autoregressive")
                    imgui.Separator(ctx)

                    if _draw_track_strip_body(p, is_drum):
                        track_params[guid] = p
                        changed = True
                finally:
                    imgui.EndChild(ctx)
            finally:
                imgui.PopID(ctx)
    finally:
        imgui.EndChild(ctx)

    return changed, clicked

# ---------------------------------------------------------------------------
# UI: Top banner
# ---------------------------------------------------------------------------

def draw_top_banner():
    """Centered wordmark across the top of the window, in a fixed font size
    -- its height never changes with the window; only its horizontal
    position (to stay centered) does."""
    imgui.PushFont(ctx, mono_font, MGPT_BANNER_FONT_SIZE)
    try:
        banner_w, _ = imgui.CalcTextSize(ctx, MGPT_BANNER)
        avail_w, _ = imgui.GetContentRegionAvail(ctx)
        imgui.SetCursorPosX(ctx, imgui.GetCursorPosX(ctx) + max(0.0, (avail_w - banner_w) / 2))
        imgui.TextColored(ctx, _signed32(LOGO_COLOR), MGPT_BANNER)
    finally:
        imgui.PopFont(ctx)

# ---------------------------------------------------------------------------
# UI: Logo + Console log
# ---------------------------------------------------------------------------

def draw_logo(width, row_h):
    """Draws the centered Metacreation Lab logo in a fixed-size child, at a
    small font size so its ASCII art fits within row_h without clipping or
    forcing the enclosing row (and therefore the outer window) taller -- an
    outer window that overflows its budgeted height is what caused the
    EndChild/End crashes fixed earlier. Shared between the Setup row (logo
    on the left, now that the window is wide enough to afford it) and
    nothing else currently, but kept as its own function rather than
    inlined so that's just a call-site change if it moves again."""
    imgui.PushFont(ctx, mono_font, LOGO_FONT_SIZE)
    logo_w, logo_h = imgui.CalcTextSize(ctx, LOGO)
    imgui.PopFont(ctx)

    imgui.BeginChild(ctx, "##logo", width, row_h)
    try:
        imgui.SetCursorPos(ctx, max(0.0, (width - logo_w) / 2),
                            max(0.0, (row_h - logo_h) / 2))
        imgui.PushFont(ctx, mono_font, LOGO_FONT_SIZE)
        try:
            imgui.TextColored(ctx, _signed32(LOGO_COLOR), LOGO)
        finally:
            imgui.PopFont(ctx)
    finally:
        imgui.EndChild(ctx)

def draw_console(row_h):
    # Read-only multiline input instead of plain Text -- lets the user
    # click-drag to select and Cmd/Ctrl+C to copy console output (e.g. to
    # paste an error message elsewhere), which Text doesn't support. Full
    # width now -- the logo that used to share this row moved up to sit
    # next to Setup instead (see loop()).
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
    so it covers the titlebar too, not just the content."""
    theme = [
        (imgui.Col_WindowBg(),           0x1A0A0AFF),
        (imgui.Col_ChildBg(),            0x140808FF),
        (imgui.Col_PopupBg(),            0x1A0A0AFF),
        (imgui.Col_TitleBg(),            0x220C0CFF),
        (imgui.Col_TitleBgActive(),      0x4D1414FF),
        (imgui.Col_Header(),             0x3D1414FF),
        (imgui.Col_HeaderHovered(),      0x5C1C1CFF),
        (imgui.Col_HeaderActive(),       0x7A2424FF),
        (imgui.Col_Button(),             0x5C1C1CFF),
        (imgui.Col_ButtonHovered(),      0x7A2424FF),
        (imgui.Col_ButtonActive(),       0x992E2EFF),
        (imgui.Col_FrameBg(),            0x2A1010FF),
        (imgui.Col_FrameBgHovered(),     0x3D1717FF),
        (imgui.Col_FrameBgActive(),      0x4D1C1CFF),
        (imgui.Col_CheckMark(),          0xE63946FF),
        (imgui.Col_SliderGrab(),         0xCC3333FF),
        (imgui.Col_SliderGrabActive(),   0xE64545FF),
        (imgui.Col_Border(),             0x5C1C1CFF),
        (imgui.Col_Separator(),          0x5C1C1CFF),
        (imgui.Col_SeparatorHovered(),   0x992E2EFF),
        (imgui.Col_SeparatorActive(),    0xE64545FF),
        (imgui.Col_Text(),               0xEDEDEDFF),
        (imgui.Col_ScrollbarBg(),        0x1A0A0AFF),
        (imgui.Col_ScrollbarGrab(),      0x5C1C1CFF),
        (imgui.Col_ScrollbarGrabHovered(), 0x7A2424FF),
        (imgui.Col_ScrollbarGrabActive(),  0x992E2EFF),
    ]
    for col, rgba in theme:
        imgui.PushStyleColor(ctx, col, _signed32(rgba))
    return len(theme)

def loop():
    global active_generation, active_batch, last_generation_result

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
        imgui.SetNextWindowSizeConstraints(ctx, 500, 300, 100000, 100000)
        # "##layout2" (invisible in the title bar -- everything after "##"
        # is ID-only, not displayed) gives this window a fresh identity with
        # no saved geometry, so the new SetNextWindowSize above actually
        # takes effect. Without it, Cond_FirstUseEver is a no-op for anyone
        # who already has ReaImGui-persisted geometry saved under the old
        # "MIDI-GPT Dashboard" id from before this layout existed -- it only
        # applies the very first time a given window id is ever seen, not
        # on every code change. Bump this suffix again in the future if the
        # default size/layout changes enough to want to reset it once more.
        visible, is_open = imgui.Begin(ctx, "MIDI-GPT Dashboard##layout2", True)

        if visible:
            try:
                draw_top_banner()
                imgui.Spacing(ctx)

                # Everything except the console lives in its own scrollable
                # child, sized to leave room for the console below it. This
                # ReaImGui build corrupts its window stack (EndChild/End
                # assertions) when the *outer* window's content overflows
                # while a fixed-height child (the console) sits at the
                # bottom -- e.g. expanding enough Track Controls sections to
                # exceed the window height. Confining the scrolling to an
                # inner child instead means the outer window's own content
                # never overflows.
                #
                # The main content area gets priority for space: as the
                # window shrinks, the console+logo row gives up height
                # first, all the way down to nothing if needed. The two
                # heights are computed to always sum to exactly usable_h --
                # never more -- because independent fixed floors (the old
                # approach) can each get satisfied individually while still
                # summing to more than the actual window has, overflowing
                # the outer window and crashing this ReaImGui build the
                # same way an expanded Track Controls section once did.
                # size_h=0 has a special "use remaining space" meaning in
                # BeginChild/InputTextMultiline, so heights are floored at
                # 1.0 rather than 0 to avoid accidentally triggering that.
                avail_w, avail_h = imgui.GetContentRegionAvail(ctx)
                usable_h = max(2.0, avail_h - 40)
                console_row_h = min(CONSOLE_ROW_HEIGHT, max(1.0, usable_h - MIN_CONTENT_HEIGHT))
                content_h = max(1.0, usable_h - console_row_h)

                imgui.BeginChild(ctx, "##main_content", 0, content_h)
                try:
                    # Setup (rarely touched once configured) shares its row
                    # with the logo, logo on the left -- now that the window
                    # is wide enough to afford it, that's a free row back
                    # instead of the logo only ever appearing next to the
                    # console. Below this row, Generate (Run Infill +
                    # progress + Global Options -- what's touched every run)
                    # and the Tracks mixer sit side by side, both visible at
                    # once, rather than switching between them -- Generate
                    # gets a fixed-ish width column since it's mostly
                    # vertical sliders; the mixer gets whatever's left, since
                    # that's the one that actually wants width (it scrolls
                    # horizontally per track).
                    imgui.SeparatorText(ctx, "Setup")
                    draw_logo(LOGO_CHILD_WIDTH, SETUP_ROW_HEIGHT)
                    imgui.SameLine(ctx)
                    imgui.BeginChild(ctx, "##setup_body", 0, SETUP_ROW_HEIGHT)
                    try:
                        setup_clicked = draw_setup_panel()
                        if setup_clicked:
                            clicked = setup_clicked
                    finally:
                        imgui.EndChild(ctx)

                    imgui.Spacing(ctx)
                    imgui.Separator(ctx)
                    imgui.Spacing(ctx)

                    avail_w, avail_h = imgui.GetContentRegionAvail(ctx)
                    generate_w = min(GENERATE_PANEL_WIDTH, max(260.0, avail_w * 0.4))

                    imgui.BeginChild(ctx, "##generate_panel", generate_w, avail_h)
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

                    imgui.SameLine(ctx)
                    imgui.BeginChild(ctx, "##tracks_panel", 0, avail_h)
                    try:
                        imgui.SeparatorText(ctx, "Tracks")
                        need_save_track, track_clicked = draw_track_controls(track_params)
                        if track_clicked:
                            clicked = track_clicked
                    finally:
                        imgui.EndChild(ctx)
                finally:
                    imgui.EndChild(ctx)

                imgui.SeparatorText(ctx, "Console")
                draw_console(console_row_h)
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
