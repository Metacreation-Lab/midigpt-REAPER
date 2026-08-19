# -*- coding: utf-8 -*-
"""
REAPER_midigpt_apply_soundfont_template.py  --  force-clone the SoundFont
template onto the selected tracks

REAPER_midigpt_setup_tracks.py only adds a cloned instrument to tracks that
don't have one yet, so it won't touch tracks that already got an empty
Sforzando (e.g. added before a SoundFont template was set). This action
replaces whatever instrument FX is on each *selected* track with a fresh
clone of the template track's instrument. Scoped to selection only, since
it overwrites -- select just the tracks you actually want replaced.
"""

from reaper_python import *

EXT_STATE_SECTION = "MIDI-GPT"
SOUNDFONT_TEMPLATE_GUID_KEY = "soundfont_template_track_guid"


class _ReaperConsole:
    def write(self, s):
        RPR_ShowConsoleMsg(s)
    def flush(self):
        pass

import sys
sys.stdout = sys.stderr = _ReaperConsole()


def get_template_track():
    guid = (RPR_GetExtState(EXT_STATE_SECTION, SOUNDFONT_TEMPLATE_GUID_KEY) or "").strip()
    if not guid:
        return None
    for i in range(RPR_CountTracks(0)):
        track = RPR_GetTrack(0, i)
        if RPR_GetSetMediaTrackInfo_String(track, "GUID", "", False)[3] == guid:
            if RPR_TrackFX_GetInstrument(track) >= 0:
                return track
            return None
    return None


def run_apply_soundfont_template():
    RPR_ClearConsole()

    template_track = get_template_track()
    if template_track is None:
        print("No SoundFont template set (or it no longer has an instrument).\n")
        print("Run 'MIDI-GPT: Use as soundfont template' on a configured track first.\n")
        return

    n_sel = RPR_CountSelectedTracks(0)
    if n_sel == 0:
        print("Select the tracks you want to replace with the SoundFont template first.\n")
        return

    template_fx = RPR_TrackFX_GetInstrument(template_track)
    template_name = RPR_GetSetMediaTrackInfo_String(template_track, "P_NAME", "", False)[3]

    RPR_Undo_BeginBlock()
    for i in range(n_sel):
        track = RPR_GetSelectedTrack(0, i)
        if track == template_track:
            continue
        name = RPR_GetSetMediaTrackInfo_String(track, "P_NAME", "", False)[3] or "(unnamed)"

        existing_fx = RPR_TrackFX_GetInstrument(track)
        if existing_fx >= 0:
            RPR_TrackFX_Delete(track, existing_fx)

        dest_idx = RPR_TrackFX_GetCount(track)
        RPR_TrackFX_CopyToTrack(template_track, template_fx, track, dest_idx, False)

        if RPR_TrackFX_GetInstrument(track) >= 0:
            print(f"{name}: cloned instrument from '{template_name}'")
        else:
            print(f"{name}: FAILED to clone instrument")
    RPR_Undo_EndBlock("MIDI-GPT: Apply soundfont template", -1)

    print("\nDone.\n")


if __name__ == "__main__":
    run_apply_soundfont_template()
