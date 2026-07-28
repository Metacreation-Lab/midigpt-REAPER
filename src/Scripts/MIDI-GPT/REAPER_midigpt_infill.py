# -*- coding: utf-8 -*-
"""
REAPER_midigpt_infill.py  --  REAPER-side MIDI-GPT client

On every run:
  1. Call GET /info to fetch loaded model metadata (capabilities, resolution, attributes).
  2. Locate Global Options JSFX and Track Options JSFX (Yellow, Prism, or Expressive).
  3. Extract MIDI from selected items in REAPER.
  4. Convert to a stateless Score JSON payload.
  5. Submit to POST /generate.
  6. Write the returned generated MIDI back to REAPER.
"""

import sys
import json
import time
import traceback
import urllib.request

from reaper_python import *
from midi_extraction import (
    extract_midi_for_mmm,
    MIDISongByMeasure,
    MIDIMeasure,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SERVER_URL = "http://127.0.0.1:3456"

GLOBAL_FX_ID = 54964318
TRACK_FX_YELLOW_ID = 349583025
TRACK_FX_EXPRESSIVE_ID = 349583026
TRACK_FX_PRISM_ID = 349583027

# ---------------------------------------------------------------------------
# Console Helper
# ---------------------------------------------------------------------------

class _ReaperConsole:
    def write(self, s):
        RPR_ShowConsoleMsg(s)
    def flush(self):
        pass

sys.stdout = sys.stderr = _ReaperConsole()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_approx(x, y, tol=0.0001):
    return abs(x - y) <= tol

def http_get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'MIDI-GPT-REAPER'})
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode('utf-8'))

def http_post(url, data_dict):
    import urllib.error
    data = json.dumps(data_dict).encode('utf-8')
    req = urllib.request.Request(
        url, 
        data=data, 
        headers={'Content-Type': 'application/json', 'User-Agent': 'MIDI-GPT-REAPER'}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode('utf-8')
            err_json = json.loads(err_body)
            detail = err_json.get("detail", err_body)
            print(f"HTTP Server Error {e.code}: {detail}\n")
        except Exception:
            print(f"HTTP Server Error {e.code}: {e.reason}\n")
        raise

# ---------------------------------------------------------------------------
# Global Options JSFX
# ---------------------------------------------------------------------------

class GlobalOptions:
    def __init__(self):
        self.temperature          = 1.0
        self.model_dim            = 4
        self.bars_per_step        = 1
        self.tracks_per_step      = 1
        self.polyphony_hard_limit = 0
        self.density_hard_limit   = 0
        self.max_attempts         = 3
        self.temp_escalation      = 1.0
        self.top_p                = 1.0
        self.top_k                = 0
        self.mask_p               = 0.0
        self.mask_k               = 0
        self.seed                 = -1
        self.checks_idx           = 3
        self.shuffle              = 0

    def to_config_dict(self, supports_token_mask=False) -> dict:
        bps = min(self.bars_per_step, self.model_dim)
        
        # Map checks index to booleans
        novelty_check = self.checks_idx in (1, 3)
        silence_check = self.checks_idx in (2, 3)

        mask_mode = "token" if supports_token_mask else "attention"

        d = {
            "temperature"           : self.temperature,
            "model_dim"             : self.model_dim,
            "bars_per_step"         : bps,
            "tracks_per_step"       : self.tracks_per_step,
            "polyphony_hard_limit"  : self.polyphony_hard_limit,
            "density_hard_limit"    : self.density_hard_limit,
            "max_attempts"          : self.max_attempts,
            "temperature_escalation": self.temp_escalation,
            "top_p"                 : self.top_p,
            "top_k"                 : self.top_k,
            "mask_p"                : self.mask_p,
            "mask_k"                : self.mask_k,
            "mask_mode"             : mask_mode,
            "novelty_check"         : novelty_check,
            "silence_check"         : silence_check,
            "shuffle"               : bool(self.shuffle),
        }
        
        if self.seed >= 0:
            d["seed"] = self.seed
            
        return d

def _locate_global_fx() -> int:
    try:
        master = RPR_GetMasterTrack(0)
        for i in range(100):
            idx = 0x1000000 + i
            if RPR_TrackFX_GetEnabled(master, idx):
                raw = RPR_TrackFX_GetParam(master, idx, 0, 0, 0)[0]
                if is_approx(raw, GLOBAL_FX_ID):
                    return idx
    except Exception:
        pass
    return -1

def get_global_options() -> GlobalOptions:
    opts = GlobalOptions()
    try:
        master = RPR_GetMasterTrack(0)
        if not master:
            return opts
        fx_loc = _locate_global_fx()
        if fx_loc == -1:
            return opts
        
        opts.temperature          = float(RPR_TrackFX_GetParam(master, fx_loc, 1, 0, 0)[0])
        opts.model_dim            = int(RPR_TrackFX_GetParam(master, fx_loc, 2, 0, 0)[0])
        opts.bars_per_step        = int(RPR_TrackFX_GetParam(master, fx_loc, 3, 0, 0)[0])
        opts.tracks_per_step      = int(RPR_TrackFX_GetParam(master, fx_loc, 4, 0, 0)[0])
        opts.polyphony_hard_limit = int(RPR_TrackFX_GetParam(master, fx_loc, 5, 0, 0)[0])
        opts.density_hard_limit   = int(RPR_TrackFX_GetParam(master, fx_loc, 6, 0, 0)[0])
        opts.max_attempts         = int(RPR_TrackFX_GetParam(master, fx_loc, 7, 0, 0)[0])
        if opts.max_attempts <= 0:
            opts.max_attempts = 3
            opts.temp_escalation = 1.0
            opts.top_p = 1.0
            opts.top_k = 0
            opts.mask_p = 0.0
            opts.mask_k = 0
            opts.seed = -1
            opts.checks_idx = 3
            opts.shuffle = 0
        else:
            opts.temp_escalation      = float(RPR_TrackFX_GetParam(master, fx_loc, 8, 0, 0)[0])
            opts.top_p                = float(RPR_TrackFX_GetParam(master, fx_loc, 9, 0, 0)[0])
            opts.top_k                = int(RPR_TrackFX_GetParam(master, fx_loc, 10, 0, 0)[0])
            opts.mask_p               = float(RPR_TrackFX_GetParam(master, fx_loc, 11, 0, 0)[0])
            opts.mask_k               = int(RPR_TrackFX_GetParam(master, fx_loc, 12, 0, 0)[0])
            opts.seed                 = int(RPR_TrackFX_GetParam(master, fx_loc, 13, 0, 0)[0])
            opts.checks_idx           = int(RPR_TrackFX_GetParam(master, fx_loc, 14, 0, 0)[0])
            opts.shuffle              = int(RPR_TrackFX_GetParam(master, fx_loc, 15, 0, 0)[0])
    except Exception as e:
        print(f"Error reading Global Options JSFX: {e}\n")
    return opts

# ---------------------------------------------------------------------------
# Track Options JSFX (Schema & Model-Specific)
# ---------------------------------------------------------------------------

def _locate_track_options_fx(track, track_fx_id: float) -> int:
    try:
        for i in range(RPR_TrackFX_GetCount(track)):
            raw = RPR_TrackFX_GetParam(track, i, 0, 0, 0)[0]
            if is_approx(raw, track_fx_id):
                return i
    except Exception:
        pass
    return -1

def get_track_prompts(num_measures: int, model_type: str, track_fx_id: float, extraction):
    """
    Read per-track options and attributes from the JSFX, returning a list of
    TrackPrompt dicts matching the structure of midigpt.inference.config.TrackPrompt.
    """
    tracks_prompts = []

    for track_info in extraction.song.track_info:
        i = track_info.track_index
        track = track_info.track
        fx_loc = _locate_track_options_fx(track, track_fx_id)

        # Default options
        is_ar = False
        is_ignored = False
        attrs = {}
        bar_attrs = {}
        is_drum_track = getattr(track_info, 'instrument', 0) == 128

        if fx_loc >= 0:
            if model_type == "expressive":
                # Expressive JSFX slider mapping:
                # slider2: key_signature (0-25)      -> track-level
                # slider3: pitch_range (0-128)        -> track-level
                # slider4: silence_proportion (0-10)  -> track-level
                # slider5: min_note_duration_q (0-6)  -> track-level
                # slider6: max_note_duration_q (0-6)  -> track-level
                # slider7: density (0-10)             -> bar-level (bar_note_density)
                # slider8: min_polyphony_q (0-10)     -> bar-level (bar_min_polyphony)
                # slider9: max_polyphony_q (0-10)     -> bar-level (bar_max_polyphony)
                # slider10: pitch_class_set (0-13)    -> bar-level
                # slider11: nomml (0-13)              -> track-level
                # slider12: autoregressive (0-1)
                # slider13: ignore (0-1)
                try:
                    key_sig   = int(RPR_TrackFX_GetParam(track, fx_loc, 1,  0, 0)[0])
                    pitch_rng = int(RPR_TrackFX_GetParam(track, fx_loc, 2,  0, 0)[0])
                    silence   = int(RPR_TrackFX_GetParam(track, fx_loc, 3,  0, 0)[0])
                    min_dur   = int(RPR_TrackFX_GetParam(track, fx_loc, 4,  0, 0)[0])
                    max_dur   = int(RPR_TrackFX_GetParam(track, fx_loc, 5,  0, 0)[0])
                    density   = int(RPR_TrackFX_GetParam(track, fx_loc, 6,  0, 0)[0])
                    min_poly  = int(RPR_TrackFX_GetParam(track, fx_loc, 7,  0, 0)[0])
                    max_poly  = int(RPR_TrackFX_GetParam(track, fx_loc, 8,  0, 0)[0])
                    pcs       = int(RPR_TrackFX_GetParam(track, fx_loc, 9,  0, 0)[0])
                    nomml     = int(RPR_TrackFX_GetParam(track, fx_loc, 10, 0, 0)[0])

                    is_ar      = bool(round(RPR_TrackFX_GetParam(track, fx_loc, 11, 0, 0)[0]))
                    is_ignored = bool(round(RPR_TrackFX_GetParam(track, fx_loc, 12, 0, 0)[0]))

                    if key_sig   > 0: attrs["key_signature"]      = key_sig - 1
                    if pitch_rng > 0: attrs["pitch_range"]         = pitch_rng - 1
                    if silence   > 0: attrs["silence_proportion"]  = silence - 1
                    if min_dur   > 0: attrs["min_note_duration"]   = min_dur - 1
                    if max_dur   > 0: attrs["max_note_duration"]   = max_dur - 1
                    if nomml     > 0: attrs["nomml"]               = nomml - 1

                    if density  > 0 and is_drum_track: bar_attrs["bar_note_density"]   = density - 1
                    if min_poly > 0: bar_attrs["bar_min_polyphony"]  = min_poly - 1
                    if max_poly > 0: bar_attrs["bar_max_polyphony"]  = max_poly - 1
                    if pcs      > 0: bar_attrs["pitch_class_set"]    = pcs - 1
                except Exception as e:
                    print(f"Error reading Expressive JSFX for track {i}: {e}\n")

            elif model_type == "prism":
                # Prism JSFX slider mapping:
                # slider2: key_signature (0-25)      -> track-level
                # slider3: pitch_range (0-128)        -> track-level
                # slider4: silence_proportion (0-10)  -> track-level
                # slider5: min_note_duration_q (0-6)  -> track-level
                # slider6: max_note_duration_q (0-6)  -> track-level
                # slider7: density (0-10)             -> bar-level (bar_note_density)
                # slider8: min_polyphony_q (0-10)     -> bar-level (bar_min_polyphony)
                # slider9: max_polyphony_q (0-10)     -> bar-level (bar_max_polyphony)
                # slider10: pitch_class_set (0-13)    -> bar-level
                # slider11: autoregressive (0-1)
                # slider12: ignore (0-1)
                try:
                    key_sig   = int(RPR_TrackFX_GetParam(track, fx_loc, 1,  0, 0)[0])
                    pitch_rng = int(RPR_TrackFX_GetParam(track, fx_loc, 2,  0, 0)[0])
                    silence   = int(RPR_TrackFX_GetParam(track, fx_loc, 3,  0, 0)[0])
                    min_dur   = int(RPR_TrackFX_GetParam(track, fx_loc, 4,  0, 0)[0])
                    max_dur   = int(RPR_TrackFX_GetParam(track, fx_loc, 5,  0, 0)[0])
                    density   = int(RPR_TrackFX_GetParam(track, fx_loc, 6,  0, 0)[0])
                    min_poly  = int(RPR_TrackFX_GetParam(track, fx_loc, 7,  0, 0)[0])
                    max_poly  = int(RPR_TrackFX_GetParam(track, fx_loc, 8,  0, 0)[0])
                    pcs       = int(RPR_TrackFX_GetParam(track, fx_loc, 9,  0, 0)[0])

                    is_ar      = bool(round(RPR_TrackFX_GetParam(track, fx_loc, 10, 0, 0)[0]))
                    is_ignored = bool(round(RPR_TrackFX_GetParam(track, fx_loc, 11, 0, 0)[0]))

                    if key_sig   > 0: attrs["key_signature"]     = key_sig - 1
                    if pitch_rng > 0: attrs["pitch_range"]        = pitch_rng - 1
                    if silence   > 0: attrs["silence_proportion"] = silence - 1
                    if min_dur   > 0: attrs["min_note_duration"]  = min_dur - 1
                    if max_dur   > 0: attrs["max_note_duration"]  = max_dur - 1

                    if density  > 0 and is_drum_track: bar_attrs["bar_note_density"]   = density - 1
                    if min_poly > 0: bar_attrs["bar_min_polyphony"]  = min_poly - 1
                    if max_poly > 0: bar_attrs["bar_max_polyphony"]  = max_poly - 1
                    if pcs      > 0: bar_attrs["pitch_class_set"]    = pcs - 1
                except Exception as e:
                    print(f"Error reading Prism JSFX for track {i}: {e}\n")

            else:
                # Yellow mapping:
                # slider2: density (0-10)             -> track-level
                # slider3: min_polyphony_q (0-10)     -> track-level
                # slider4: max_polyphony_q (0-10)     -> track-level
                # slider5: min_note_duration_q (0-6)  -> track-level
                # slider6: max_note_duration_q (0-6)  -> track-level
                # slider7: polyphony_hard_limit (0-16)
                # slider8: autoregressive (0-1)
                # slider9: ignore (0-1)
                try:
                    density    = int(RPR_TrackFX_GetParam(track, fx_loc, 1, 0, 0)[0])
                    min_poly   = int(RPR_TrackFX_GetParam(track, fx_loc, 2, 0, 0)[0])
                    max_poly   = int(RPR_TrackFX_GetParam(track, fx_loc, 3, 0, 0)[0])
                    min_dur    = int(RPR_TrackFX_GetParam(track, fx_loc, 4, 0, 0)[0])
                    max_dur    = int(RPR_TrackFX_GetParam(track, fx_loc, 5, 0, 0)[0])
                    poly_limit = int(RPR_TrackFX_GetParam(track, fx_loc, 6, 0, 0)[0])

                    is_ar      = bool(round(RPR_TrackFX_GetParam(track, fx_loc, 7, 0, 0)[0]))
                    is_ignored = bool(round(RPR_TrackFX_GetParam(track, fx_loc, 8, 0, 0)[0]))

                    if density    > 0 and is_drum_track: attrs["note_density"]     = density - 1
                    if min_poly   > 0: attrs["min_polyphony"]    = min_poly - 1
                    if max_poly   > 0: attrs["max_polyphony"]    = max_poly - 1
                    if min_dur    > 0: attrs["min_note_duration"] = min_dur - 1
                    if max_dur    > 0: attrs["max_note_duration"] = max_dur - 1
                    if poly_limit > 0: attrs["onset_polyphony"]  = poly_limit
                except Exception as e:
                    print(f"Error reading Yellow JSFX for track {i}: {e}\n")

        # Determine target bars to generate
        if is_ignored:
            bars_to_gen = []
        elif is_ar:
            bars_to_gen = list(range(num_measures))
        else:
            bars_to_gen = [b for b in range(num_measures) if extraction.masks.is_masked(i, b)]

        # Apply bar-level attrs to every bar being generated
        per_bar_attributes = (
            {b: dict(bar_attrs) for b in bars_to_gen}
            if bar_attrs and bars_to_gen else {}
        )

        tracks_prompts.append({
            "id": i,
            "bars": bars_to_gen,
            "autoregressive": is_ar,
            "ignore": is_ignored,
            "mask_bars": [],
            "attributes": attrs,
            "bar_attributes": per_bar_attributes,
        })

    return tracks_prompts

# ---------------------------------------------------------------------------
# Score Serialization
# ---------------------------------------------------------------------------

def song_to_score_dict(song: MIDISongByMeasure, resolution: int) -> dict:
    """Convert REAPER extraction representation directly to midigpt Score dict"""
    tracks = []
    
    # Base start time offset
    origin_secs = None
    for track_measures in song.measures:
        for m in track_measures:
            if m is not None:
                t = float(m.start_time)
                if origin_secs is None or t < origin_secs:
                    origin_secs = t
    if origin_secs is None:
        origin_secs = 0.0

    def _secs_to_ticks(secs: float, bpm: float) -> int:
        return int(round(secs * (bpm / 60.0) * resolution))

    for track_idx in range(song.num_tracks):
        ti = song.get_track_info(track_idx)
        instrument = ti.instrument if ti else 0
        track_type = "drum" if instrument == 128 else "melodic"
        
        bars = []
        for bar_idx in range(song.num_measures):
            measure = song.get_measure(track_idx, bar_idx)
            if measure:
                bpm = measure.tempo if measure.tempo > 0 else 120.0
                ts_num, ts_denom = measure.time_signature
                
                notes = []
                for note in measure.notes:
                    onset_ticks = _secs_to_ticks(note.start_time, bpm)
                    duration_ticks = _secs_to_ticks(note.end_time - note.start_time, bpm)
                    notes.append({
                        "pitch": note.pitch,
                        "velocity": note.velocity,
                        "onset_ticks": onset_ticks,
                        "duration_ticks": max(1, duration_ticks),
                        "delta": 0
                    })
                
                bars.append({
                    "ts_numerator": ts_num,
                    "ts_denominator": ts_denom,
                    "future": False,
                    "notes": notes
                })
            else:
                bars.append({
                    "ts_numerator": 4,
                    "ts_denominator": 4,
                    "future": False,
                    "notes": []
                })
        
        tracks.append({
            "instrument": 0 if track_type == "drum" else instrument,
            "track_type": track_type,
            "bars": bars
        })
        
    return {
        "resolution": resolution,
        "tempo": 500000,
        "tracks": tracks
    }

# ---------------------------------------------------------------------------
# Result Write-Back
# ---------------------------------------------------------------------------

def write_generated_score(score_dict: dict, extraction) -> None:
    from midi_extraction import MIDINote, REAPERMIDIWriter

    resolution = score_dict.get("resolution", 12)
    writer = REAPERMIDIWriter(extraction.tempo_map)

    for track_idx, track_data in enumerate(score_dict.get("tracks", [])):
        track_info = extraction.song.get_track_info(track_idx)
        if not track_info:
            continue

        for bar_idx, bar_data in enumerate(track_data.get("bars", [])):
            # Only write back generated bars (marked as masks or autoregressive)
            if not extraction.masks.is_masked(track_idx, bar_idx):
                # Check if track prompt had autoregressive enabled
                is_ar = False
                for tp in extraction.track_prompts:
                    if tp["id"] == track_idx and tp["autoregressive"]:
                        is_ar = True
                        break
                if not is_ar:
                    continue

            measure = extraction.song.get_measure(track_idx, bar_idx)
            if not measure:
                continue

            bpm = measure.tempo if measure.tempo > 0 else 120.0
            secs_per_tick = 60.0 / (bpm * resolution)

            measure.notes = [
                MIDINote(
                    pitch      = n["pitch"],
                    velocity   = n["velocity"],
                    start_time = n["onset_ticks"] * secs_per_tick,
                    end_time   = (n["onset_ticks"] + n["duration_ticks"]) * secs_per_tick,
                )
                for n in bar_data.get("notes", [])
            ]

            take = writer._get_midi_take_for_measure(track_info.track, measure)
            if not take:
                print(f"Warning: no MIDI take for track {track_info.track_name}, "
                      f"measure {measure.measure_number}\n")
                continue

            writer._delete_notes_in_measure(take, measure)
            writer._write_measure_notes(take, measure, notes_are_selected=True)
            RPR_MIDI_Sort(take)

# ---------------------------------------------------------------------------
# Main Workflow
# ---------------------------------------------------------------------------

def run_midigpt_infill():
    RPR_ClearConsole()

    # ---- 1. Fetch server info --------------------------------------------- #
    print("Connecting to MIDI-GPT HTTP server...\n")
    try:
        info = http_get(f"{SERVER_URL}/info")
    except Exception as e:
        print(f"Cannot reach server at {SERVER_URL}:\n  {e}\n")
        print("Please make sure start_midigpt_server.sh is running.\n")
        return

    checkpoint = info.get("checkpoint", "unknown")
    capabilities = info.get("capabilities", {})
    attributes = info.get("attributes", {})
    resolution = info.get("resolution", 12)

    if "nomml" in attributes:
        model_type = "expressive"
        track_fx_id = TRACK_FX_EXPRESSIVE_ID
    elif "key_signature" in attributes:
        model_type = "prism"
        track_fx_id = TRACK_FX_PRISM_ID
    else:
        model_type = "yellow"
        track_fx_id = TRACK_FX_YELLOW_ID

    print(f"Active Checkpoint : {checkpoint}")
    print(f"Model Type        : {model_type.upper()}")
    print(f"Tick Resolution   : {resolution}\n")

    # ---- 2. Read global options ------------------------------------------ #
    options = get_global_options()
    print("Global options loaded.")

    # ---- 3. Extract MIDI ------------------------------------------------- #
    print("Extracting MIDI from REAPER...\n")
    try:
        extraction = extract_midi_for_mmm(
            mask_selected_items=True,
            mask_empty_items=False,
        )
    except Exception:
        print(f"Extraction failed:\n{traceback.format_exc()}\n")
        return

    num_measures = extraction.song.num_measures
    if num_measures == 0:
        print("No MIDI found in selection.\n")
        return
    if extraction.masks.count == 0:
        print("No measures to infill -- select some MIDI items first.\n")
        return

    print(f"Tracks   : {extraction.song.num_tracks}")
    print(f"Measures : {extraction.start_measure}-{extraction.end_measure}")
    print(f"Masked   : {extraction.masks.count} (track, bar) positions\n")

    # ---- 4. Read per-track options --------------------------------------- #
    track_prompts = get_track_prompts(num_measures, model_type, track_fx_id, extraction)
    # Stash prompts in extraction result for write-back filtering
    extraction.track_prompts = track_prompts

    print("Track prompts built:")
    for tp in track_prompts:
        if tp["bars"] or tp["autoregressive"] or tp["ignore"]:
            print(f"  Track {tp['id']}: bars_to_gen={tp['bars']} AR={tp['autoregressive']} ignore={tp['ignore']} attrs={tp['attributes']} bar_attrs={tp['bar_attributes']}")
    print()

    # ---- 5. Serialize to Score JSON -------------------------------------- #
    print("Converting MIDI data...")
    score_dict = song_to_score_dict(extraction.song, resolution)

    # ---- 6. Build GenerationRequest payload ------------------------------ #
    request_dict = {
        "score": score_dict,
        "request": {
            "tracks": track_prompts,
            "config": options.to_config_dict(capabilities.get("supports_token_mask", False))
        }
    }

    # ---- 7. POST to /generate -------------------------------------------- #
    print("Generating MIDI via MIDI-GPT HTTP server (this may take a few seconds)...")
    start_t = time.time()
    try:
        response = http_post(f"{SERVER_URL}/generate", request_dict)
    except Exception as e:
        print(f"\nGeneration request failed: {e}\n")
        return
    elapsed = time.time() - start_t

    if "score" not in response:
        print(f"\nServer error: {response.get('detail', 'Unknown error')}\n")
        return

    print(f"Generation completed successfully in {elapsed:.2f}s.\n")

    # ---- 8. Write back --------------------------------------------------- #
    print("Writing generated MIDI to REAPER...\n")
    try:
        write_generated_score(response["score"], extraction)
    except Exception:
        print(f"Write-back failed:\n{traceback.format_exc()}\n")
        return

    print("Done.\n")
    RPR_Undo_OnStateChange("MIDI-GPT Infill")

if __name__ == "__main__":
    run_midigpt_infill()
