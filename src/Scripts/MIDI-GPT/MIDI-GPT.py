# -*- coding: utf-8 -*-
"""
@description MIDI-GPT
@author Paul Triana
@version 1.0
@about
  The main MIDI-GPT dashboard: one window for the whole workflow (server/
  model selection, global generation settings, per-track controls, running
  generation, and the console/information log). Native ReaImGui table
  layout, fixed size.
"""

import platform
import sys
from reaper_python import *
sys.path.append(RPR_GetResourcePath() + "/Scripts/ReaTeam Extensions/API")
import imgui

from midigpt_dashboard import (
    console_panel, generation_panel, global_settings_panel, notify, setup_panel, themes, tracks_panel,
)
from midigpt_dashboard.constants import VALIDATION_LABELS, DEFAULT_TRACK_SETTINGS, NOTE_DURATION_LABELS
from midigpt_dashboard.logic import DashboardLogic
from midigpt_dashboard.state import DashboardState

MGPT_BANNER = (
    "\u2588\u2588\u2588\u2557   \u2588\u2588\u2588\u2557      \u2588\u2588\u2588\u2588\u2588\u2588\u2557   \u2588\u2588\u2588\u2588\u2588\u2588\u2557   \u2588\u2588\u2588\u2588\u2588\u2557              \u2588\u2588\u2588\u2588\u2588\u2588\u2557   \u2588\u2588\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\n"
    "\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2551      \u2588\u2588\u2554\u2550\u2550\u2550\u255d   \u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557  \u255a\u2550\u2588\u2588\u2554\u255d             \u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255d   \u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557 \u255a\u2550\u2550\u2588\u2588\u2554\u2550\u2550\u255d\n"
    "\u2588\u2588\u2554\u2588\u2588\u2588\u2588\u2554\u2588\u2588\u2551      \u2588\u2588\u2551       \u2588\u2588\u2551  \u2588\u2588\u2551    \u2588\u2588\u2551    \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2551  \u2588\u2588\u2588\u2557  \u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d    \u2588\u2588\u2551   \n"
    "\u2588\u2588\u2551\u255a\u2588\u2588\u2554\u255d\u2588\u2588\u2551      \u2588\u2588\u2551       \u2588\u2588\u2551  \u2588\u2588\u2551    \u2588\u2588\u2551    \u255a\u2550\u2550\u2550\u2550\u2550\u2550\u255d  \u2588\u2588\u2551   \u2588\u2588\u2551  \u2588\u2588\u2554\u2550\u2550\u2550\u255d     \u2588\u2588\u2551   \n"
    "\u2588\u2588\u2551 \u255a\u2550\u255d \u2588\u2588\u2551  \u25e2\u2588\u2588\u2588\u2588\u2588\u2557       \u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d  \u2588\u2588\u2588\u2588\u2588\u2557             \u255a\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d  \u2588\u2588\u2551         \u2588\u2588\u2551   \n"
    "\u255a\u2550\u255d     \u255a\u2550\u255d  \u2588\u2588\u2588\u2588\u2588\u2588\u2551       \u255a\u2550\u2550\u2550\u2550\u2550\u255d   \u255a\u2550\u2550\u2550\u2550\u255d              \u255a\u2550\u2550\u2550\u2550\u2550\u255d   \u255a\u2550\u255d         \u255a\u2550\u255d   \n"
    "             \u255a\u2588\u2588\u2588\u2588\u2588\u2554\u255d"
)
MGPT_BANNER_FONT_SIZE = 5.5

# The banner only lines up in a monospaced font that has every glyph it
# uses -- a missing font or glyph falls back to one with different advance
# widths, and the columns drift. Menlo is macOS-only. On Windows, Consolas
# has all of them at one width except U+25E2, which is swapped for
# U+2584, the nearest glyph it does have. Elsewhere, ReaImGui's generic
# "monospace" family.
# (Every non-ASCII character in this file, including here, must stay a
# \uXXXX escape rather than a literal glyph -- REAPER's ReaScript loader
# reads .py files with the platform's default codec rather than honoring
# the coding cookie above, and that default is plain ASCII on some
# platforms/setups, which raised a UnicodeDecodeError on a literal glyph
# here.)
if platform.system() == "Darwin":
    BANNER_FONT_FAMILY = "Menlo"
elif platform.system() == "Windows":
    BANNER_FONT_FAMILY = "Consolas"
    MGPT_BANNER = MGPT_BANNER.replace("\u25e2", "\u2584")
else:
    BANNER_FONT_FAMILY = "monospace"

# Grid height proportions (15%, 55%, 30%)
ROW_RATIOS = [0.15, 0.55, 0.30]

# Cell padding pushed onto the grid table (StyleVar_CellPadding, below).
# Every table cell reserves this much padding on each side; a child sized
# to the full column/row would spill past its cell -- and, at the grid's
# outer edge, past the window itself, which is what was cutting the grid
# off on the right and along the bottom. Each BeginChild below is sized to
# its column/row minus 2x this amount so it fits inside its padded cell.
CELL_PADDING_X = 2
CELL_PADDING_Y = 2

# Extra breathing room reserved beyond the grid itself, on top of what the
# cell-padding accounting above already keeps clipping-free.
RIGHT_PADDING = 0
BOTTOM_PADDING = 0

MODEL_TYPE = "yellow"
dashboard_state = DashboardState()
log_lines = []
logic = None


class _DashboardConsole:
    def __init__(self):
        self.buffer = ""

    def write(self, text):
        self.buffer += text
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            log_lines.append(line)
        del log_lines[:-500]

    def flush(self):
        pass


sys.stdout = sys.stderr = _DashboardConsole()
GLOBAL_SETTINGS = {
    "temperature": 1.0,
    "model_dim": 4,
    "bars_per_step": 1,
    "tracks_per_step": 1,
    "polyphony_hard_limit": 0,
    "density_hard_limit": 0,
    "max_attempts": 3,
    "temp_escalation": 1.0,
    "top_p": 1.0,
    "top_k": 0,
    "mask_p": 0.0,
    "mask_k": 0,
    "seed": -1,
    "checks_idx": 3,
    "shuffle": 0,
    "num_candidates": 1,
    "manual_seed": False,
    "polyphony_limit_enabled": False,
    "density_limit_enabled": False,
    "temp_escalation_enabled": False,
    "top_p_enabled": False,
    "top_k_enabled": False,
    "mask_p_enabled": False,
    "mask_k_enabled": False,
}

def draw_logo_panel(cell_w, cell_h):
    """(0,0) Banner / Logo section"""
    imgui.PushFont(ctx, mono_font, MGPT_BANNER_FONT_SIZE)
    banner_w, banner_h = imgui.CalcTextSize(ctx, MGPT_BANNER)
    imgui.PopFont(ctx)

    imgui.BeginChild(ctx, "##banner", cell_w, cell_h, False)
    try:
        imgui.SetCursorPos(ctx, max(0.0, (cell_w - banner_w) / 2),
                            max(0.0, (cell_h - banner_h) / 2))
        imgui.PushFont(ctx, mono_font, MGPT_BANNER_FONT_SIZE)
        try:
            imgui.Text(ctx, MGPT_BANNER)
        finally:
            imgui.PopFont(ctx)
    finally:
        imgui.EndChild(ctx)


def draw_setup_panel(window_center):
    """(0,1) Setup controls section"""
    return setup_panel.draw(ctx, logic, window_center)


def draw_global_settings_panel_legacy():
    """(1,0) Global generation settings section"""
    params = GLOBAL_SETTINGS
    if not imgui.BeginTabBar(ctx, "GlobalSettingsTabs"):
        return

    if imgui.BeginTabItem(ctx, "Plan")[0]:
        imgui.SeparatorText(ctx, "Generation Plan")
        c, v = imgui.SliderInt(ctx, "Context Length (Bars)", params["model_dim"], 2, 16)
        if c:
            params["model_dim"] = v
        c, v = imgui.SliderInt(ctx, "Bars per Step", min(params["bars_per_step"], params["model_dim"]), 1, params["model_dim"])
        if c:
            params["bars_per_step"] = v
        c, v = imgui.SliderInt(ctx, "Tracks per Step", params["tracks_per_step"], 1, 16)
        if c:
            params["tracks_per_step"] = v

        imgui.SeparatorText(ctx, "Reproducibility")
        c, selected = imgui.RadioButtonEx(ctx, "Manual seed", 0 if params["manual_seed"] == True else 1, 0)
        if c:
            params["manual_seed"] = not params["manual_seed"]
        imgui.SameLine(ctx)
        imgui.BeginDisabled(ctx, not params["manual_seed"])
        c, v = imgui.InputInt(ctx, "Seed", max(0, params["seed"]), 1, 100)
        if c:
            params["seed"] = max(0, v)
        imgui.EndDisabled(ctx)
        if params["manual_seed"] == False:
            params["seed"] = -1
            imgui.TextDisabled(ctx, "The server selects a fresh seed for each generation.")
        imgui.EndTabItem(ctx)

    if imgui.BeginTabItem(ctx, "Sampling")[0]:
        imgui.SeparatorText(ctx, "Sampling")
        c, v = imgui.SliderDouble(ctx, "Temperature", params["temperature"], 0.1, 3.0, "%.2f")
        if c:
            params["temperature"] = v
        c, v = imgui.Checkbox(ctx, "Enable Top-p", params["top_p_enabled"])
        if c:
            params["top_p_enabled"] = v
        imgui.BeginDisabled(ctx, not params["top_p_enabled"])
        c, v = imgui.SliderDouble(ctx, "Top-p", params["top_p"], 0.0, 1.0, "%.2f")
        if c:
            params["top_p"] = v
        imgui.EndDisabled(ctx)
        if not params["top_p_enabled"]:
            params["top_p"] = 1.0
        c, v = imgui.Checkbox(ctx, "Enable Top-k", params["top_k_enabled"])
        if c:
            params["top_k_enabled"] = v
        imgui.BeginDisabled(ctx, not params["top_k_enabled"])
        c, v = imgui.SliderInt(ctx, "Top-k", params["top_k"], 1, 500)
        if c:
            params["top_k"] = v
        imgui.EndDisabled(ctx)
        if not params["top_k_enabled"]:
            params["top_k"] = 0
        imgui.SeparatorText(ctx, "Advanced Sampling")
        c, v = imgui.Checkbox(ctx, "Enable mask probability", params["mask_p_enabled"])
        if c:
            params["mask_p_enabled"] = v
        imgui.BeginDisabled(ctx, not params["mask_p_enabled"])
        c, v = imgui.SliderDouble(ctx, "Mask probability", params["mask_p"], 0.0, 0.95, "%.2f")
        if c:
            params["mask_p"] = v
        imgui.EndDisabled(ctx)
        if not params["mask_p_enabled"]:
            params["mask_p"] = 0.0
        c, v = imgui.Checkbox(ctx, "Enable mask count", params["mask_k_enabled"])
        if c:
            params["mask_k_enabled"] = v
        imgui.BeginDisabled(ctx, not params["mask_k_enabled"])
        c, v = imgui.SliderInt(ctx, "Mask count", params["mask_k"], 1, 100)
        if c:
            params["mask_k"] = v
        imgui.EndDisabled(ctx)
        if not params["mask_k_enabled"]:
            params["mask_k"] = 0
        imgui.EndTabItem(ctx)

    if imgui.BeginTabItem(ctx, "Constraints")[0]:
        imgui.SeparatorText(ctx, "Musical Constraints")
        c, v = imgui.Checkbox(ctx, "Limit polyphony", params["polyphony_limit_enabled"])
        if c:
            params["polyphony_limit_enabled"] = v
        imgui.BeginDisabled(ctx, not params["polyphony_limit_enabled"])
        c, v = imgui.SliderInt(ctx, "Maximum voices", params["polyphony_hard_limit"], 1, 32)
        if c:
            params["polyphony_hard_limit"] = v
        imgui.EndDisabled(ctx)
        if not params["polyphony_limit_enabled"]:
            params["polyphony_hard_limit"] = 0
            imgui.TextDisabled(ctx, "Polyphony limit: Off")

        c, v = imgui.Checkbox(ctx, "Limit note density", params["density_limit_enabled"])
        if c:
            params["density_limit_enabled"] = v
        imgui.BeginDisabled(ctx, not params["density_limit_enabled"])
        c, v = imgui.SliderInt(ctx, "Maximum notes", params["density_hard_limit"], 1, 64)
        if c:
            params["density_hard_limit"] = v
        imgui.EndDisabled(ctx)
        if not params["density_limit_enabled"]:
            params["density_hard_limit"] = 0
            imgui.TextDisabled(ctx, "Note density limit: Off")
        imgui.EndTabItem(ctx)

    if imgui.BeginTabItem(ctx, "Quality")[0]:
        imgui.SeparatorText(ctx, "Validation")
        checks_idx = params["checks_idx"]
        for i, label in enumerate(VALIDATION_LABELS):
            c, checks_idx = imgui.RadioButtonEx(ctx, label, checks_idx, i)
            if c:
                params["checks_idx"] = checks_idx
            if i < 3:
                imgui.SameLine(ctx)
        c, v = imgui.Checkbox(ctx, "Shuffle processing steps", bool(params["shuffle"]))
        if c:
            params["shuffle"] = int(v)
        imgui.SeparatorText(ctx, "Recovery")
        c, v = imgui.SliderInt(ctx, "Maximum attempts", params["max_attempts"], 1, 10)
        if c:
            params["max_attempts"] = v
        c, v = imgui.Checkbox(ctx, "Increase temperature on retry", params["temp_escalation_enabled"])
        if c:
            params["temp_escalation_enabled"] = v
        imgui.BeginDisabled(ctx, not params["temp_escalation_enabled"])
        c, v = imgui.SliderDouble(ctx, "Retry temperature multiplier", params["temp_escalation"], 1.0, 3.0, "%.2f")
        if c:
            params["temp_escalation"] = v
        imgui.EndDisabled(ctx)
        if not params["temp_escalation_enabled"]:
            params["temp_escalation"] = 1.0
        imgui.EndTabItem(ctx)

    imgui.EndTabBar(ctx)


def draw_global_settings_panel():
    """(1,0) Global generation settings section."""
    global_settings_panel.draw(ctx, GLOBAL_SETTINGS, logic.model_type)


def draw_tracks_panel():
    """(1,1) Track controls section"""
    tracks_panel.draw(ctx, dashboard_state, logic.model_type)


def draw_console_panel():
    """(2,0) Console output section"""
    return console_panel.draw(ctx, log_lines, logic)


def draw_generation_panel():
    """(2,1) Generation controls and context/info section"""
    return generation_panel.draw(ctx, GLOBAL_SETTINGS, logic)

def _context_lost():
    """True (after saying why, once, in REAPER's own console) when
    ReaImGui has no valid context for this window. Seen on Linux under
    native Wayland (issue #7): ReaImGui can't open its window and drops the
    context, and every later ImGui call fails -- so the loop stops instead
    of repeating those errors every frame. REAPER's console, not the
    dashboard's: there is no dashboard to print to."""
    if imgui.ValidatePtr(ctx, 'ImGui_Context*'):
        return False
    message = (
        "MIDI-GPT: ReaImGui could not open the dashboard window, so the "
        "dashboard has stopped.\n"
    )
    if platform.system() == "Linux":
        message += (
            "On Wayland, start REAPER under XWayland instead:\n"
            "    GDK_BACKEND=x11 reaper\n"
        )
    message += (
        "If that doesn't help, update ReaImGui by running the MIDI-GPT "
        "installer again, then restart REAPER.\n"
        "More: https://github.com/Metacreation-Lab/midigpt-REAPER/issues/7\n"
    )
    RPR_ShowConsoleMsg(message)
    return True


def init():
    global ctx, mono_font, logic
    ctx = imgui.CreateContext('MIDI-GPT Dashboard')
    mono_font = imgui.CreateFont(BANNER_FONT_FAMILY)
    imgui.Attach(ctx, mono_font)
    logic = DashboardLogic(GLOBAL_SETTINGS, dashboard_state, log_lines)
    logic.refresh_model_info()
    loop()

def loop():
    if _context_lost():
        return
    logic.poll_generation()
    pending_action = None
    # 1. Set fixed window size (Always sets size to 800x600 every frame)
    imgui.SetNextWindowSize(ctx, 800, 600, imgui.Cond_Always())

    # 2. Add NoResize flag to lock window dimensions
    window_flags = (
        imgui.WindowFlags_NoResize() |
        imgui.WindowFlags_NoScrollbar() |
        imgui.WindowFlags_NoScrollWithMouse()
    )

    # Pushed before Begin (so it colors the window's own chrome too) and
    # popped once at the very end regardless of visibility -- see
    # settings_panel.py for where the theme is actually picked.
    theme_color_count = themes.push(ctx)
    visible, open_state = imgui.Begin(ctx, 'MIDI-GPT', True, window_flags)
    if visible:
        # The server-address popup (setup_panel.py) centers itself over
        # this window specifically, not the OS display, so it needs this
        # window's own screen position/size rather than GetMainViewport().
        window_x, window_y = imgui.GetWindowPos(ctx)
        window_w, window_h = imgui.GetWindowSize(ctx)
        window_center = (window_x + window_w / 2, window_y + window_h / 2)

        notify.draw(ctx, window_center)

        # Get available dimensions and reserve breathing room beyond the
        # grid's right/bottom edges (see RIGHT_PADDING/BOTTOM_PADDING above).
        raw_w, raw_h = imgui.GetContentRegionAvail(ctx)
        avail_w = raw_w - RIGHT_PADDING
        avail_h = raw_h - BOTTOM_PADDING

        imgui.PushStyleVar(ctx, imgui.StyleVar_CellPadding(), CELL_PADDING_X, CELL_PADDING_Y)
        imgui.PushStyleVar(ctx, imgui.StyleVar_WindowPadding(), 0, 0)

        # 3. Create 2-Column Table Layout
        table_flags = imgui.TableFlags_SizingFixedFit() | imgui.TableFlags_NoHostExtendY()
        if imgui.BeginTable(ctx, 'GridTable', 2, table_flags, avail_w, avail_h):

            # Setup equal 50% width columns. Children are sized to
            # col_w/row_h minus the cell padding on both sides (see
            # CELL_PADDING_X/Y above) so they fit exactly inside their
            # padded cell instead of overflowing it.
            col_w = avail_w * 0.5
            child_w = col_w - 2 * CELL_PADDING_X
            imgui.TableSetupColumn(ctx, 'Col1', imgui.TableColumnFlags_WidthFixed(), col_w)
            imgui.TableSetupColumn(ctx, 'Col2', imgui.TableColumnFlags_WidthFixed(), col_w)

            # --- ROW 0 (15% height) ---
            row_0_h = int(avail_h * ROW_RATIOS[0])
            child_h_0 = row_0_h - 2 * CELL_PADDING_Y
            imgui.TableNextRow(ctx, imgui.TableRowFlags_None(), row_0_h)

            # Cell (0,0) - Logo
            imgui.TableSetColumnIndex(ctx, 0)
            logo_visible = imgui.BeginChild(ctx, "CellChild_Logo", child_w, child_h_0, False)
            if logo_visible:
                draw_logo_panel(child_w, child_h_0)
            imgui.EndChild(ctx)

            # Cell (0,1) - Setup
            imgui.TableSetColumnIndex(ctx, 1)
            setup_visible = imgui.BeginChild(ctx, "CellChild_Setup", child_w, child_h_0, False)
            if setup_visible:
                pending_action = draw_setup_panel(window_center) or pending_action
            imgui.EndChild(ctx)

            # --- ROW 1 (55% height) ---
            row_1_h = int(avail_h * ROW_RATIOS[1])
            child_h_1 = row_1_h - 2 * CELL_PADDING_Y
            imgui.TableNextRow(ctx, imgui.TableRowFlags_None(), row_1_h)

            # Cell (1,0) - Global settings
            imgui.TableSetColumnIndex(ctx, 0)
            global_settings_visible = imgui.BeginChild(ctx, "CellChild_GlobalSettings", child_w, child_h_1, False)
            if global_settings_visible:
                draw_global_settings_panel()
            imgui.EndChild(ctx)

            # Cell (1,1) - Tracks
            imgui.TableSetColumnIndex(ctx, 1)
            tracks_visible = imgui.BeginChild(ctx, "CellChild_Tracks", child_w, child_h_1, False)
            if tracks_visible:
                draw_tracks_panel()
            imgui.EndChild(ctx)

            # --- ROW 2 (30% height) ---
            row_2_h = int(avail_h * ROW_RATIOS[2])
            child_h_2 = row_2_h - 2 * CELL_PADDING_Y
            imgui.TableNextRow(ctx, imgui.TableRowFlags_None(), row_2_h)

            # Cell (2,0) - Console
            imgui.TableSetColumnIndex(ctx, 0)
            console_visible = imgui.BeginChild(ctx, "CellChild_Console", child_w, child_h_2, False)
            if console_visible:
                pending_action = draw_console_panel() or pending_action
            imgui.EndChild(ctx)

            # Cell (2,1) - Generation
            imgui.TableSetColumnIndex(ctx, 1)
            generation_visible = imgui.BeginChild(ctx, "CellChild_Generation", child_w, child_h_2, False)
            if generation_visible:
                pending_action = draw_generation_panel() or pending_action
            imgui.EndChild(ctx)

            imgui.EndTable(ctx)

        imgui.PopStyleVar(ctx, 2)
        imgui.End(ctx)
    imgui.PopStyleColor(ctx, theme_color_count)

    logic.persist_if_changed()
    if pending_action:
        try:
            logic.run_action(pending_action)
        except Exception as error:
            print(f"Dashboard action failed: {error}\n")
            notify.error(f"Action failed: {error}")

    if open_state:
        RPR_defer("loop()")

RPR_defer("init()")