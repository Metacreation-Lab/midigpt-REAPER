"""Server and track setup controls."""

import importlib

from reaper_python import *

import imgui

# These sibling REAPER action scripts have spaces in their filenames (e.g.
# "MIDI-GPT Generate.py"), which isn't valid `import` statement syntax --
# importlib.import_module() takes the literal string instead, resolved via
# the same path-based finder REAPER puts this script's own directory on.
infill = importlib.import_module("MIDI-GPT Generate")
setup_tracks = importlib.import_module("MIDI-GPT Setup Tracks")

from . import hints, settings_panel, themes

_SERVER_POPUP_ID = "Set MIDI-GPT Server##server_popup"
# Draft text for the server-URL popup's input field. Module-level rather
# than DashboardState since it's purely a transient UI value (reset fresh
# from the real server URL every time the popup opens) -- nothing needs to
# persist it across frames beyond the edit session itself.
_server_url_draft = ""

# Width given to the "Architecture" label when it shares a line with the
# model combo (see draw()).
_ARCHITECTURE_WIDTH = 100

_TRACK_OPTIONS_POPUP_ID = "Set Up Tracks##track_options_popup"
_TRACK_CONFIRM_POPUP_ID = "Confirm Track Instruments##track_confirm_popup"

# ["(unresolved -- skip)"] + every GM melodic instrument + "drums" -- the
# per-track instrument picker in the confirmation popup below.
_INSTRUMENT_CHOICES = ["(unresolved -- skip)"] + list(setup_tracks.GM_INTERNAL_NAMES) + ["drums"]

# "Setup Tracks"/"Setup Selected Tracks" is a 2-step flow -- an options
# popup (what to set up, how to detect instruments, and, when scoped to a
# selection, whether to replace an existing instrument), then, only if
# something needs a human's eyes on it, a per-track confirmation popup --
# so this has to survive across frames rather than living in local
# variables. The three *_setup_* fields are sticky across runs (the
# session's last choice becomes the next default); the rest is working
# state for whichever run is currently in progress.
_wizard = {
    "name_only": False,
    "confirm_detection": False,
    "replace_existing": False,
    "scope": "all",  # "all" | "selected"
    "error": None,
    "tracks": [],
    "instruments": {},
    "needs_confirmation": [],
    "open_confirm_popup_pending": False,
}


def _truncate_to_width(ctx, text, max_width):
    """Truncate text with a trailing "..." if it's wider than max_width in
    the current font, instead of letting a long model/checkpoint name clip
    abruptly or push the rest of the line past the panel edge."""
    if imgui.CalcTextSize(ctx, text)[0] <= max_width:
        return text
    ellipsis = "..."
    budget = max_width - imgui.CalcTextSize(ctx, ellipsis)[0]
    if budget <= 0:
        return ellipsis
    truncated = text
    while truncated and imgui.CalcTextSize(ctx, truncated)[0] > budget:
        truncated = truncated[:-1]
    return truncated + ellipsis


def _draw_server_popup(ctx, window_center):
    """Server-address editor as a ReaImGui modal instead of the native
    RPR_GetUserInputs dialog the dashboard used to shell out to -- centered
    over the dashboard window and dims it behind, like any other modal
    (BeginPopupModal's default behavior), rather than popping up a
    separate OS-native window in front of/behind it."""
    global _server_url_draft
    action = None
    imgui.SetNextWindowPos(ctx, window_center[0], window_center[1], imgui.Cond_Appearing(), 0.5, 0.5)
    # The popup would otherwise inherit the dashboard's global
    # WindowPadding(0, 0) (pushed in MIDI-GPT.py so the
    # grid's child panels sit flush against their cells), leaving the
    # input/buttons jammed against the popup's edges.
    imgui.PushStyleVar(ctx, imgui.StyleVar_WindowPadding(), 16, 16)
    visible, _ = imgui.BeginPopupModal(ctx, _SERVER_POPUP_ID, None, imgui.WindowFlags_AlwaysAutoResize())
    imgui.PopStyleVar(ctx, 1)
    if visible:
        # No label here -- the popup's own title bar ("Set MIDI-GPT
        # Server") already says what this is.
        imgui.SetNextItemWidth(ctx, 320)
        # No InputTextFlags_EnterReturnsTrue: with it, ImGui only writes the
        # edited text back to _server_url_draft when Enter is pressed, so
        # typing a URL and clicking Save saved the old one. Without it the
        # draft tracks every keystroke, and Enter is detected separately.
        _, _server_url_draft = imgui.InputText(ctx, "##server_url_input", _server_url_draft)
        entered = imgui.IsItemDeactivated(ctx) and (
            imgui.IsKeyPressed(ctx, imgui.Key_Enter()) or imgui.IsKeyPressed(ctx, imgui.Key_KeypadEnter())
        )
        hints.show(ctx, "setup.server_popup.url_input")
        if imgui.Button(ctx, "Save", 100, 0) or entered:
            if infill.set_server_url(_server_url_draft):
                action = "refresh_model"
            imgui.CloseCurrentPopup(ctx)
        imgui.SameLine(ctx)
        if imgui.Button(ctx, "Cancel", 100, 0):
            imgui.CloseCurrentPopup(ctx)
        imgui.EndPopup(ctx)
    return action


def _draw_model_combo(ctx, logic, max_width):
    """Custom combo (BeginCombo/Selectable) rather than the plain Combo
    helper, so the closed-state preview can be ellipsis-truncated to
    max_width -- Combo's own preview just hard-clips a long name with no
    "..." indicator."""
    action = None
    current = logic.selected_model if logic.selected_model in logic.available_models else logic.available_models[0]
    imgui.SetNextItemWidth(ctx, max_width)
    if imgui.BeginCombo(ctx, "##model", _truncate_to_width(ctx, current, max_width - 24)):
        for model in logic.available_models:
            is_selected = model == logic.selected_model
            clicked, _ = imgui.Selectable(ctx, model, is_selected)
            if clicked and model != logic.selected_model:
                logic.selected_model = model
                infill.set_selected_model(model)
                action = "refresh_model"
            if is_selected:
                imgui.SetItemDefaultFocus(ctx)
        imgui.EndCombo(ctx)
    return action


def _instrument_to_choice_index(instrument):
    if instrument is None:
        return 0
    if instrument == 128:
        return len(_INSTRUMENT_CHOICES) - 1
    return instrument + 1


def _choice_index_to_instrument(index):
    if index <= 0:
        return None
    if index == len(_INSTRUMENT_CHOICES) - 1:
        return 128
    return index - 1


def _collect_scope_tracks(scope):
    if scope == "selected":
        return [RPR_GetSelectedTrack(0, i) for i in range(RPR_CountSelectedTracks(0))]
    return [RPR_GetTrack(0, i) for i in range(RPR_CountTracks(0))]


def _draw_track_options_popup(ctx, window_center):
    """Step 1: what this run should do -- name only vs. name + instruments,
    trust auto-detection vs. confirm every track, and (selection-scoped
    only) whether to replace an instrument that's already there. "Run"
    detects instruments for the chosen tracks and, if anything needs a
    human's input (detection failed, or "let me confirm" was picked),
    hands off to the confirmation popup below instead of applying
    anything yet."""
    action = None
    imgui.SetNextWindowPos(ctx, window_center[0], window_center[1], imgui.Cond_Appearing(), 0.5, 0.5)
    imgui.PushStyleVar(ctx, imgui.StyleVar_WindowPadding(), 16, 16)
    visible, _ = imgui.BeginPopupModal(ctx, _TRACK_OPTIONS_POPUP_ID, None, imgui.WindowFlags_AlwaysAutoResize())
    imgui.PopStyleVar(ctx, 1)
    if visible:
        scope = _wizard["scope"]
        imgui.Text(ctx, f"Set up {'all' if scope == 'all' else 'the selected'} track(s)")

        imgui.SeparatorText(ctx, "What to set up")
        choice = 1 if _wizard["name_only"] else 0
        changed, choice = imgui.RadioButtonEx(ctx, "Track names + instruments (Sforzando + Arachno)", choice, 0)
        hints.show(ctx, "setup.track_options.mode")
        if changed:
            _wizard["name_only"] = choice == 1
        changed, choice = imgui.RadioButtonEx(ctx, "Track names only", choice, 1)
        hints.show(ctx, "setup.track_options.mode")
        if changed:
            _wizard["name_only"] = choice == 1
        if not _wizard["name_only"]:
            imgui.TextDisabled(ctx, "Optional -- skip this if you're handling synthesis yourself.")

        imgui.SeparatorText(ctx, "Instrument detection")
        choice = 1 if _wizard["confirm_detection"] else 0
        changed, choice = imgui.RadioButtonEx(ctx, "Auto-detect", choice, 0)
        hints.show(ctx, "setup.track_options.detection")
        if changed:
            _wizard["confirm_detection"] = choice == 1
        changed, choice = imgui.RadioButtonEx(ctx, "Auto-detect, but let me confirm/override each one", choice, 1)
        hints.show(ctx, "setup.track_options.detection")
        if changed:
            _wizard["confirm_detection"] = choice == 1

        if scope == "selected" and not _wizard["name_only"]:
            imgui.SeparatorText(ctx, "If a track already has an instrument")
            choice = 1 if _wizard["replace_existing"] else 0
            changed, choice = imgui.RadioButtonEx(ctx, "Skip it (leave as-is)", choice, 0)
            hints.show(ctx, "setup.track_options.replace")
            if changed:
                _wizard["replace_existing"] = choice == 1
            changed, choice = imgui.RadioButtonEx(ctx, "Replace it", choice, 1)
            hints.show(ctx, "setup.track_options.replace")
            if changed:
                _wizard["replace_existing"] = choice == 1

        imgui.Separator(ctx)
        if imgui.Button(ctx, "Run", 100, 0):
            tracks = _collect_scope_tracks(scope)
            if not tracks:
                _wizard["error"] = (
                    "No tracks in the project." if scope == "all" else "Select at least one track first."
                )
            else:
                _wizard["error"] = None
                instruments = setup_tracks.detect_instruments(tracks)
                needs_confirmation = (
                    list(tracks) if _wizard["confirm_detection"]
                    else [track for track in tracks if instruments[track] is None]
                )
                _wizard["tracks"] = tracks
                _wizard["instruments"] = instruments
                _wizard["needs_confirmation"] = needs_confirmation
                _wizard["replace_existing"] = _wizard["replace_existing"] if scope == "selected" else False
                imgui.CloseCurrentPopup(ctx)
                if needs_confirmation:
                    _wizard["open_confirm_popup_pending"] = True
                else:
                    action = "run_track_setup"
        imgui.SameLine(ctx)
        if imgui.Button(ctx, "Cancel", 100, 0):
            _wizard["error"] = None
            imgui.CloseCurrentPopup(ctx)
        if _wizard["error"]:
            imgui.TextColored(ctx, themes.error_color(), _wizard["error"])

        imgui.EndPopup(ctx)
    return action


def _draw_track_confirm_popup(ctx, window_center):
    """Step 2 (only when something needs a human's input): one instrument
    picker per track that failed auto-detection, or -- with "let me
    confirm/override" selected -- every track, pre-filled with the
    detected guess (or "(unresolved -- skip)"). "Apply" hands the final
    per-track choices off to logic.run_action("run_track_setup"), which
    calls apply_track_setup() (from MIDI-GPT Setup Tracks.py) with them."""
    action = None
    imgui.SetNextWindowPos(ctx, window_center[0], window_center[1], imgui.Cond_Appearing(), 0.5, 0.5)
    imgui.PushStyleVar(ctx, imgui.StyleVar_WindowPadding(), 16, 16)
    visible, _ = imgui.BeginPopupModal(ctx, _TRACK_CONFIRM_POPUP_ID, None, imgui.WindowFlags_AlwaysAutoResize())
    imgui.PopStyleVar(ctx, 1)
    if visible:
        imgui.Text(ctx, "Confirm each track's instrument before applying.")
        imgui.TextDisabled(ctx, "Pre-filled with the best guess from each track's MIDI content.")

        tracks = _wizard["needs_confirmation"]
        list_h = min(300, 28 * len(tracks) + 8)
        imgui.BeginChild(ctx, "##track_confirm_list", 440, list_h, True)
        for track in tracks:
            guid = RPR_GetSetMediaTrackInfo_String(track, "GUID", "", False)[3]
            imgui.PushID(ctx, guid)
            name = RPR_GetSetMediaTrackInfo_String(track, "P_NAME", "", False)[3] or "(unnamed)"
            imgui.Text(ctx, _truncate_to_width(ctx, name, 190))
            imgui.SameLine(ctx, 200)
            imgui.SetNextItemWidth(ctx, -1)
            index = _instrument_to_choice_index(_wizard["instruments"].get(track))
            changed, index = imgui.Combo(ctx, "##instrument", index, "\0".join(_INSTRUMENT_CHOICES) + "\0")
            if changed:
                _wizard["instruments"][track] = _choice_index_to_instrument(index)
            imgui.PopID(ctx)
        imgui.EndChild(ctx)

        imgui.Separator(ctx)
        if imgui.Button(ctx, "Apply", 100, 0):
            action = "run_track_setup"
            imgui.CloseCurrentPopup(ctx)
        imgui.SameLine(ctx)
        if imgui.Button(ctx, "Cancel", 100, 0):
            imgui.CloseCurrentPopup(ctx)
        imgui.EndPopup(ctx)
    return action


def get_pending_track_setup():
    """The finalized choices from the last completed Setup Tracks wizard
    run (see _wizard above) -- read once by logic.run_action() when it
    handles the "run_track_setup" action."""
    return {
        "tracks": _wizard["tracks"],
        "instruments": _wizard["instruments"],
        "name_only": _wizard["name_only"],
        "replace_existing": _wizard["replace_existing"],
    }


def server_down_help(server_url):
    """Where to look when the server can't be reached. The server's own
    window (or log) says why it stopped -- most often, at startup, that the
    model on Hugging Face needs its license accepted and a token saved."""
    host = server_url.split("://", 1)[-1].split("/", 1)[0].rsplit(":", 1)[0]
    if host in ("127.0.0.1", "localhost", "::1", "[::1]"):
        return (
            "Is the server running? Start it with 'Start MIDI-GPT Server' on "
            "your Desktop. If its window shows an error, that says why it "
            "stopped -- for example, the model license on Hugging Face not "
            "accepted yet (see Hugging Face Access in the README)."
        )
    return (
        f"Is the server at {server_url} running? Its window or log on that "
        "machine says why it stopped."
    )


def draw(ctx, logic=None, window_center=(0, 0)):
    action = None
    server_url = logic.server_url() if logic is not None else "127.0.0.1"

    imgui.Text(ctx, f"Server: {server_url}")
    hints.show(ctx, "setup.server_url")
    imgui.SameLine(ctx)
    if imgui.Button(ctx, "Change...##server"):
        global _server_url_draft
        _server_url_draft = server_url
        imgui.OpenPopup(ctx, _SERVER_POPUP_ID)
    hints.show(ctx, "setup.change_server")
    if logic is not None:
        action = _draw_server_popup(ctx, window_center) or action

    imgui.SameLine(ctx)
    if imgui.Button(ctx, "Settings##open_settings"):
        imgui.OpenPopup(ctx, settings_panel.SETTINGS_POPUP_ID)
    settings_panel.draw(ctx, window_center)

    if logic is not None and logic.available_models:
        # Model combo and architecture share a line -- the combo takes
        # whatever's left after the architecture label's fixed slice.
        avail_w, _ = imgui.GetContentRegionAvail(ctx)
        combo_w = max(60.0, avail_w - _ARCHITECTURE_WIDTH - 8)
        action = _draw_model_combo(ctx, logic, combo_w) or action
        hints.show(ctx, "setup.model")
        imgui.SameLine(ctx)
        imgui.TextDisabled(ctx, _truncate_to_width(ctx, logic.model_type, _ARCHITECTURE_WIDTH))
        hints.show(ctx, "setup.architecture")
    else:
        # No model list means the last /models query failed (the server was
        # down or unreachable) -- nothing retries on its own, so offer it.
        imgui.TextDisabled(ctx, "Model: server not reachable")
        # Always shown, not only in hint mode: this is the moment a user
        # needs to know where the reason is.
        if logic is not None:
            imgui.SetItemTooltip(ctx, server_down_help(server_url))
        imgui.SameLine(ctx)
        if imgui.Button(ctx, "Retry##retry_server") and logic is not None:
            action = "refresh_model"
        hints.show(ctx, "setup.retry_server")

    if imgui.Button(ctx, "Setup Tracks"):
        _wizard["scope"] = "all"
        _wizard["error"] = None
        imgui.OpenPopup(ctx, _TRACK_OPTIONS_POPUP_ID)
    hints.show(ctx, "setup.setup_tracks")
    imgui.SameLine(ctx)
    if imgui.Button(ctx, "Setup Selected Tracks"):
        _wizard["scope"] = "selected"
        _wizard["error"] = None
        imgui.OpenPopup(ctx, _TRACK_OPTIONS_POPUP_ID)
    hints.show(ctx, "setup.setup_selected_tracks")
    imgui.SameLine(ctx)
    if imgui.Button(ctx, "Reset Parameters"):
        action = "reset"
    hints.show(ctx, "setup.reset")
    action = _draw_track_options_popup(ctx, window_center) or action
    if _wizard["open_confirm_popup_pending"]:
        # Deferred to here (still this same frame, just outside the options
        # popup's own Begin/End block) rather than calling OpenPopup from
        # inside _draw_track_options_popup itself, right after that popup's
        # own CloseCurrentPopup -- opening a second popup while still
        # nested in the first one's block is asking for trouble.
        _wizard["open_confirm_popup_pending"] = False
        imgui.OpenPopup(ctx, _TRACK_CONFIRM_POPUP_ID)
    action = _draw_track_confirm_popup(ctx, window_center) or action
    return action
