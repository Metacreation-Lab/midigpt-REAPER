# -*- coding: utf-8 -*-
"""
REAPER_midigpt_set_soundfont_template.py  --  mark a track as the SoundFont template

Select a track whose Sforzando instance already has your GM SoundFont
imported (Instrument > import > your .sf2), then run this action. Its
track GUID is stored via ExtState; REAPER_midigpt_setup_tracks.py clones
this track's instrument (via TrackFX_CopyToTrack, state and all) onto any
track that doesn't have an instrument yet, so the SoundFont only needs to
be imported once, manually, ever.
"""

from reaper_python import *

EXT_STATE_SECTION = "MIDI-GPT"
SOUNDFONT_TEMPLATE_GUID_KEY = "soundfont_template_track_guid"


def run_set_soundfont_template():
    RPR_ClearConsole()

    track = RPR_GetSelectedTrack(0, 0)
    if not track:
        print("Select a track with a configured Sforzando instrument first.\n")
        return

    if RPR_TrackFX_GetInstrument(track) < 0:
        print("Selected track has no instrument FX loaded -- add Sforzando and\n")
        print("import your SoundFont into it first.\n")
        return

    guid = RPR_GetSetMediaTrackInfo_String(track, "GUID", "", False)[3]
    RPR_SetExtState(EXT_STATE_SECTION, SOUNDFONT_TEMPLATE_GUID_KEY, guid, True)

    name = RPR_GetSetMediaTrackInfo_String(track, "P_NAME", "", False)[3] or "(unnamed)"
    print(f"SoundFont template set to track: {name}\n")
    print("'MIDI-GPT: Setup tracks' will clone this instrument onto any track\n")
    print("that doesn't have one yet. Use 'MIDI-GPT: Apply soundfont template\n")
    print("to selected tracks' to replace instruments on tracks that already\n")
    print("have one (e.g. empty Sforzandos added before this template existed).\n")


if __name__ == "__main__":
    run_set_soundfont_template()
