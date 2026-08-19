# -*- coding: utf-8 -*-
"""
REAPER_midigpt_setup_tracks.py  --  auto-configure MIDI-GPT tracks

For every track in the project:
  1. Detect the track's intended GM instrument from the actual MIDI content
     (channel 10 -> drums, otherwise the track's first Program Change
     event) rather than the track name -- importing a multi-track MIDI file
     usually gives every track the same name (the file name), so name
     matching alone can't tell tracks apart. Tracks with no channel/PC info
     to go on are prompted for individually, via a native dropdown list on
     macOS (falls back to a single keyword-entry dialog elsewhere/if
     cancelled). The track is then renamed to the resolved instrument's
     canonical name (see INSTRUMENTS.md), so tracks are readable and
     distinguishable at a glance.
  2. Add an instrument if the track has none yet:
       - If a SoundFont template track has been set (see
         REAPER_midigpt_set_soundfont_template.py), clone its already-loaded
         Sforzando instance via TrackFX_CopyToTrack -- no re-importing the
         SoundFont file per track.
       - Otherwise add a blank Sforzando and prompt to import the SoundFont
         once, then mark that track as the template.
  3. Try to auto-select the instrument's GM program inside the plugin via
     TrackFX_SetPreset, using the resolved instrument's canonical name as
     the preset name. This only works once you've manually saved a REAPER
     FX preset under that exact name for each instrument you use (from
     Sforzando's own preset-save menu, one time ever) -- see README.md.

This automates the manual per-track setup described in VST.md -- run it
right after importing a MIDI file, or after adding new tracks, instead of
adding the instrument plugin by hand on every track. Until you've saved
presets for an instrument, selecting its program inside Sforzando is still
a manual last step -- the console output tells you which GM instrument each
track was resolved to, so you know what to pick.

Safe to re-run: a track's instrument is only ever touched by this script if
the script added it in the first place (tracked per-track in the project),
and its preset is only set until confirmed once -- after that, or on any
instrument this script didn't add, re-running never overwrites a manual
change. This also means a preset that didn't take effect on one run (e.g.
the instrument was still loading) gets retried automatically on the next.
"""

import sys
import platform
import subprocess
import time

from reaper_python import *
from midi_extraction import INST_TO_MATCHING_STRINGS

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

EXT_STATE_SECTION = "MIDI-GPT"
SOUNDFONT_PATH_KEY = "soundfont_path"
SOUNDFONT_TEMPLATE_GUID_KEY = "soundfont_template_track_guid"

# FX presets are saved under this prefix (e.g. "MIDI-GPT: xylophone") so they
# sort together and never collide with a user's own same-named presets.
PRESET_PREFIX = "MIDI-GPT: "

# Tried in order; REAPER's FX lookup accepts partial/case-insensitive names,
# but the exact display string varies a bit by OS/vendor build.
INSTRUMENT_CANDIDATES = [
    "VSTi: sforzando (Plogue Art et Technologie Inc)",
    "VST3i: sforzando (Plogue Art et Technologie Inc)",
    "sforzando",
]

# GM program 0-127 -> canonical name, exactly matching INSTRUMENTS.md.
GM_INTERNAL_NAMES = [
    "acoustic_grand_piano", "bright_acoustic_piano", "electric_grand_piano", "honky_tonk_piano",
    "electric_piano_1", "electric_piano_2", "harpsichord", "clavi",
    "celesta", "glockenspiel", "music_box", "vibraphone",
    "marimba", "xylophone", "tubular_bells", "dulcimer",
    "drawbar_organ", "percussive_organ", "rock_organ", "church_organ",
    "reed_organ", "accordion", "harmonica", "tango_accordion",
    "acoustic_guitar_nylon", "acoustic_guitar_steel", "electric_guitar_jazz", "electric_guitar_clean",
    "electric_guitar_muted", "overdriven_guitar", "distortion_guitar", "guitar_harmonics",
    "acoustic_bass", "electric_bass_finger", "electric_bass_pick", "fretless_bass",
    "slap_bass_1", "slap_bass_2", "synth_bass_1", "synth_bass_2",
    "violin", "viola", "cello", "contrabass",
    "tremolo_strings", "pizzicato_strings", "orchestral_harp", "timpani",
    "string_ensemble_1", "string_ensemble_2", "synth_strings_1", "synth_strings_2",
    "choir_aahs", "voice_oohs", "synth_voice", "orchestra_hit",
    "trumpet", "trombone", "tuba", "muted_trumpet",
    "french_horn", "brass_section", "synth_brass_1", "synth_brass_2",
    "soprano_sax", "alto_sax", "tenor_sax", "baritone_sax",
    "oboe", "english_horn", "bassoon", "clarinet",
    "piccolo", "flute", "recorder", "pan_flute",
    "blown_bottle", "shakuhachi", "whistle", "ocarina",
    "lead_1_square", "lead_2_sawtooth", "lead_3_calliope", "lead_4_chiff",
    "lead_5_charang", "lead_6_voice", "lead_7_fifths", "lead_8_bass__lead",
    "pad_1_new_age", "pad_2_warm", "pad_3_polysynth", "pad_4_choir",
    "pad_5_bowed", "pad_6_metallic", "pad_7_halo", "pad_8_sweep",
    "fx_1_rain", "fx_2_soundtrack", "fx_3_crystal", "fx_4_atmosphere",
    "fx_5_brightness", "fx_6_goblins", "fx_7_echoes", "fx_8_sci_fi",
    "sitar", "banjo", "shamisen", "koto",
    "kalimba", "bag_pipe", "fiddle", "shanai",
    "tinkle_bell", "agogo", "steel_drums", "woodblock",
    "taiko_drum", "melodic_tom", "synth_drum", "reverse_cymbal",
    "guitar_fret_noise", "breath_noise", "seashore", "bird_tweet",
    "telephone_ring", "helicopter", "applause", "gunshot",
]


class _ReaperConsole:
    def write(self, s):
        RPR_ShowConsoleMsg(s)
    def flush(self):
        pass

sys.stdout = sys.stderr = _ReaperConsole()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_ext_state(key, default=""):
    val = RPR_GetExtState(EXT_STATE_SECTION, key)
    val = (val or "").strip()
    return val if val else default

def get_track_name(track):
    return RPR_GetSetMediaTrackInfo_String(track, "P_NAME", "", False)[3]

def set_track_name(track, name):
    RPR_GetSetMediaTrackInfo_String(track, "P_NAME", name, True)

def gm_internal_name(instrument):
    if instrument == 128:
        return "drums"
    if 0 <= instrument < len(GM_INTERNAL_NAMES):
        return GM_INTERNAL_NAMES[instrument]
    return f"program_{instrument}"

GM_NAME_TO_INSTRUMENT = {name: i for i, name in enumerate(GM_INTERNAL_NAMES)}
GM_NAME_TO_INSTRUMENT["drums"] = 128

# ---------------------------------------------------------------------------
# Instrument detection (from MIDI content, not track name)
# ---------------------------------------------------------------------------

def _find_program_change(take):
    _, _, _, cc_cnt, _ = RPR_MIDI_CountEvts(take, 0, 0, 0)
    for c in range(cc_cnt):
        cc = RPR_MIDI_GetCC(take, c, 0, 0, 0, 0, 0, 0, 0)
        # cc: (retval, take, ccidx, selected, muted, ppqpos, chanmsg, chan, msg2, msg3)
        if cc[0] and cc[6] == 0xC0:
            return cc[8]
    return None

def detect_track_instrument(track):
    """Best-effort GM instrument detection straight from MIDI content:
    channel 10 (drums) wins; otherwise the track's first Program Change
    event, if any. Returns None if neither is present."""
    for j in range(RPR_CountTrackMediaItems(track)):
        item = RPR_GetTrackMediaItem(track, j)
        take = RPR_GetActiveTake(item)
        if not take or not RPR_TakeIsMIDI(take):
            continue

        _, _, note_cnt, _, _ = RPR_MIDI_CountEvts(take, 0, 0, 0)
        for n in range(min(note_cnt, 32)):
            note = RPR_MIDI_GetNote(take, n, 0, 0, 0, 0, 0, 0, 0)
            # note: (retval, take, noteidx, selected, muted, startppq, endppq, chan, pitch, vel)
            if note[0] and note[7] == 9:
                return 128

        program = _find_program_change(take)
        if program is not None:
            return program
    return None

def keyword_to_instrument(keyword):
    keyword = keyword.strip().lower()
    if not keyword:
        return None
    for inst_num, patterns in INST_TO_MATCHING_STRINGS.items():
        for pattern in patterns:
            if pattern in keyword:
                return inst_num
    return None

def _osascript_choose_from_list(title, prompt, options):
    """macOS-only native list picker (a real dropdown/list dialog), via
    AppleScript's 'choose from list'. Returns the chosen string, or None if
    unavailable, cancelled, or the option isn't installed (rare)."""
    def esc(s):
        return s.replace("\\", "\\\\").replace('"', '\\"')
    items = ", ".join(f'"{esc(o)}"' for o in options)
    script = (
        f'set chosen to choose from list {{{items}}} '
        f'with title "{esc(title)}" with prompt "{esc(prompt)}"\n'
        f'if chosen is false then\n'
        f'    return ""\n'
        f'else\n'
        f'    return item 1 of chosen\n'
        f'end if'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=180,
        )
        out = result.stdout.strip()
        return out if out else None
    except Exception:
        return None

def pick_instrument_dropdown(track_name):
    """Native list-picker dialog listing every GM instrument, so the user
    selects instead of typing. Currently macOS only (AppleScript); returns
    None elsewhere so callers fall back to keyword entry."""
    if platform.system() != "Darwin":
        return None
    options = GM_INTERNAL_NAMES + ["drums"]
    choice = _osascript_choose_from_list(
        "MIDI-GPT", f"Instrument for track: {track_name}", options
    )
    return GM_NAME_TO_INSTRUMENT.get(choice) if choice else None

def resolve_track_instruments(tracks):
    """Map track -> GM instrument number, reading real MIDI content first,
    then falling back to the track's current name if it's already an exact
    canonical instrument name (e.g. a blank track resolved on a previous
    run -- it has no MIDI content to detect from, so without this check
    it would be re-prompted on every single run forever). Tracks that
    still can't be resolved (e.g. freshly-created tracks, or an imported
    file where every track shares the file's name) are prompted for
    one-by-one, via a native dropdown list on macOS, falling back to a
    single keyword-entry dialog for whatever's left elsewhere/unresolved."""
    resolved = {}
    ambiguous = []
    for track in tracks:
        instrument = detect_track_instrument(track)
        if instrument is None:
            instrument = GM_NAME_TO_INSTRUMENT.get((get_track_name(track) or "").strip())
        if instrument is not None:
            resolved[track] = instrument
        else:
            ambiguous.append(track)

    still_ambiguous = []
    for track in ambiguous:
        instrument = pick_instrument_dropdown(get_track_name(track) or "(unnamed)")
        if instrument is not None:
            resolved[track] = instrument
        else:
            still_ambiguous.append(track)

    if still_ambiguous:
        captions = ",".join(
            f"{get_track_name(t) or '(unnamed)'} - keyword (e.g. piano/bass/drums)"
            for t in still_ambiguous
        )
        defaults = ",".join("" for _ in still_ambiguous)
        ret, _, _, _, csv_out, _ = RPR_GetUserInputs(
            "MIDI-GPT: Track Instruments (could not auto-detect from MIDI)",
            len(still_ambiguous),
            captions,
            defaults,
            1024,
        )
        if ret:
            values = csv_out.split(",")
            for track, value in zip(still_ambiguous, values):
                instrument = keyword_to_instrument(value)
                if instrument is not None:
                    resolved[track] = instrument

    return resolved

# ---------------------------------------------------------------------------
# Instrument (Sforzando + SoundFont template)
# ---------------------------------------------------------------------------

def get_soundfont_template_track():
    guid = get_ext_state(SOUNDFONT_TEMPLATE_GUID_KEY, "")
    if not guid:
        return None
    for i in range(RPR_CountTracks(0)):
        track = RPR_GetTrack(0, i)
        if RPR_GetSetMediaTrackInfo_String(track, "GUID", "", False)[3] == guid:
            if RPR_TrackFX_GetInstrument(track) >= 0:
                return track
            return None
    return None

# ---------------------------------------------------------------------------
# Per-track ownership/state, so re-running never touches a track's instrument
# once the script has confirmed its preset, or once the instrument turns out
# to be something the user added/changed by hand. Stored in the project
# (SetProjExtState), keyed by track GUID -- survives saves, doesn't leak
# across projects.
# ---------------------------------------------------------------------------

def get_track_guid(track):
    return RPR_GetSetMediaTrackInfo_String(track, "GUID", "", False)[3]

def is_owned(track):
    return RPR_GetProjExtState(0, EXT_STATE_SECTION, f"owned_{get_track_guid(track)}", "", 8)[0] > 0

def mark_owned(track):
    RPR_SetProjExtState(0, EXT_STATE_SECTION, f"owned_{get_track_guid(track)}", "1")

def get_applied_preset(track):
    ret, _, _, _, value, _ = RPR_GetProjExtState(0, EXT_STATE_SECTION, f"applied_preset_{get_track_guid(track)}", "", 512)
    return value if ret > 0 else ""

def set_applied_preset(track, preset_name):
    RPR_SetProjExtState(0, EXT_STATE_SECTION, f"applied_preset_{get_track_guid(track)}", preset_name)

def is_sforzando(track, fx_index):
    name = RPR_TrackFX_GetFXName(track, fx_index, "", 256)[3]
    return "sforzando" in name.lower()

def ensure_instrument(track, template_track, instrument):
    """Add/clone the instrument (only if this script hasn't already handled
    this track), then try to auto-select its GM program via a REAPER FX
    preset named after the canonical instrument name (see 'MIDI-GPT: Use as
    soundfont template' docs / README for how to create these presets once,
    from Sforzando's own preset-save menu)."""
    fx_index = RPR_TrackFX_GetInstrument(track)
    if fx_index >= 0:
        if not is_owned(track) and is_sforzando(track, fx_index):
            # Sforzando is the only instrument this script ever adds, so a
            # track with one and no ownership record predates ownership
            # tracking -- adopt it rather than leaving it stuck forever.
            mark_owned(track)
        if is_owned(track):
            return ensure_preset(track, instrument, "instrument already present")
        return "instrument already present (added by you -- left alone)"

    if template_track is not None and track != template_track:
        template_fx = RPR_TrackFX_GetInstrument(template_track)
        dest_idx = RPR_TrackFX_GetCount(track)
        RPR_TrackFX_CopyToTrack(template_track, template_fx, track, dest_idx, False)
        if RPR_TrackFX_GetInstrument(track) >= 0:
            mark_owned(track)
            # Give the clone's own (separately async) chunk restore time to
            # settle before we touch its preset, or our selection can get
            # clobbered a moment later by that still-in-flight restore.
            time.sleep(0.6)
            return ensure_preset(track, instrument, "cloned instrument from SoundFont template track")

    for name in INSTRUMENT_CANDIDATES:
        idx = RPR_TrackFX_AddByName(track, name, False, -1)
        if idx >= 0:
            mark_owned(track)
            # A saved "MIDI-GPT: <name>" preset embeds the full SoundFont
            # reference itself, so it can configure a brand new, never-used
            # Sforzando instance directly -- no template/clone needed as
            # long as that preset already exists.
            time.sleep(0.6)
            status = ensure_preset(track, instrument, "added Sforzando")
            if "selected preset" in status or "confirmed" in status:
                return status
            return (f"{status} -- no template set either; import the SoundFont manually, then run "
                    "'MIDI-GPT: Use as soundfont template' on this track")

    return "FAILED to add Sforzando -- add it manually (see VST.md)"

def select_preset(track, fx_index, preset_name, attempts=8, delay=0.4):
    """TrackFX_SetPreset can report success but not actually take effect yet
    if the instrument (e.g. a just-cloned Sforzando) hasn't finished loading
    its SoundFont internally -- verify via TrackFX_GetPreset and retry
    briefly rather than silently leaving it on the wrong/no program."""
    for _ in range(attempts):
        RPR_TrackFX_SetPreset(track, fx_index, preset_name)
        current = RPR_TrackFX_GetPreset(track, fx_index, "", 256)[3]
        if current == preset_name:
            return True
        time.sleep(delay)
    return False

def ensure_preset(track, instrument, status):
    """Best-effort: select the FX preset matching the resolved instrument's
    canonical name, if one has been saved for it -- but only on tracks this
    script created the instrument on (see is_owned), and only up until the
    point our selection is confirmed. Once confirmed, or once the active
    preset no longer matches what we last confirmed (the user changed it),
    this is a no-op -- re-running never overwrites a manual choice."""
    if instrument is None:
        return status
    fx_index = RPR_TrackFX_GetInstrument(track)
    if fx_index < 0:
        return status

    preset_name = PRESET_PREFIX + gm_internal_name(instrument)
    applied = get_applied_preset(track)
    current = RPR_TrackFX_GetPreset(track, fx_index, "", 256)[3]

    if applied:
        if current == applied:
            return f"{status}, preset '{applied}' confirmed"
        return f"{status}, preset changed since -- leaving it alone"

    if current == preset_name:
        set_applied_preset(track, preset_name)
        return f"{status}, preset '{preset_name}' confirmed"

    if select_preset(track, fx_index, preset_name):
        set_applied_preset(track, preset_name)
        return f"{status}, selected preset '{preset_name}'"
    return f"{status}, no '{preset_name}' preset saved yet (or it's still loading -- will retry next run)"

# ---------------------------------------------------------------------------
# Main Workflow
# ---------------------------------------------------------------------------

def run_setup_tracks():
    RPR_ClearConsole()

    template_track = get_soundfont_template_track()
    if template_track is not None:
        print(f"SoundFont template: {get_track_name(template_track)}\n")
    else:
        print("No SoundFont template set -- new instruments will be added empty.")
        print("Load your SoundFont into one track's Sforzando, then run")
        print("'MIDI-GPT: Use as soundfont template' on it so future tracks clone it.\n")

    num_tracks = RPR_CountTracks(0)
    tracks = [RPR_GetTrack(0, i) for i in range(num_tracks)]
    if not tracks:
        print("No tracks in project.\n")
        return

    print(f"Configuring {len(tracks)} track(s)...\n")
    instruments = resolve_track_instruments(tracks)

    RPR_Undo_BeginBlock()
    for track in tracks:
        instrument = instruments.get(track)
        if instrument is not None:
            set_track_name(track, gm_internal_name(instrument))
        name = get_track_name(track) or "(unnamed)"

        inst_result = ensure_instrument(track, template_track, instrument)
        instrument_note = f"instrument: {gm_internal_name(instrument)}" if instrument is not None else "instrument: unresolved"
        print(f"{name}: {inst_result}; {instrument_note}")
    RPR_Undo_EndBlock("MIDI-GPT: Setup tracks", -1)

    print("\nDone. Any track without a 'selected preset ...' result above still needs")
    print("its instrument picked manually inside Sforzando (Instrument > converted > sf2 > ...),")
    print("or a matching FX preset saved for it -- see README.md.\n")

if __name__ == "__main__":
    run_setup_tracks()
