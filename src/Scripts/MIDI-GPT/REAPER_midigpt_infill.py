# -*- coding: utf-8 -*-
"""
REAPER_midigpt_infill.py  --  REAPER-side MIDI-GPT client

On every run:
  1. Call GET /info to fetch loaded model metadata (capabilities, resolution, attributes).
  2. Read Global Options and per-track options saved by REAPER_midigpt_dashboard.py.
  3. Extract MIDI from selected items in REAPER.
  4. Convert to a stateless Score JSON payload.
  5. Submit to POST /generate.
  6. Write the returned generated MIDI back to REAPER.
"""

import sys
import copy
import json
import time
import uuid
import threading
import traceback
import urllib.request
import urllib.parse

from reaper_python import *
from midi_extraction import (
    extract_midi_for_mmm,
    MIDISongByMeasure,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_SERVER_URL = "http://127.0.0.1:3456"
EXT_STATE_SECTION = "MIDI-GPT"
EXT_STATE_KEY = "server_url"
EXT_STATE_MODEL_KEY = "selected_model"

def get_server_url():
    """Server address, configurable via the 'MIDI-GPT: Set server address'
    action (persisted in REAPER's ExtState). Falls back to localhost."""
    url = RPR_GetExtState(EXT_STATE_SECTION, EXT_STATE_KEY)
    url = (url or "").strip()
    return url.rstrip("/") if url else DEFAULT_SERVER_URL

def set_server_url(url):
    """Persists the MIDI-GPT server URL, normalizing a bare host:port into
    a full http:// URL and stripping any trailing slash -- same
    normalization REAPER_midigpt_set_server.py's dialog already applies.
    Returns the normalized URL, or None if given nothing to save (an empty
    field commits nothing rather than clearing back to the default).
    A plain ExtState write, not a blocking call, so callers may run this
    directly inside an ImGui frame (see set_selected_model above)."""
    url = (url or "").strip()
    if not url:
        return None
    if "://" not in url:
        url = f"http://{url}"
    url = url.rstrip("/")
    RPR_SetExtState(EXT_STATE_SECTION, EXT_STATE_KEY, url, True)
    return url

def get_selected_model():
    """Model id to request, chosen via the dashboard's Model dropdown
    (persisted in REAPER's ExtState). Empty string means "let the server
    use its own default_model" -- /info and /generate are both called
    without a model argument in that case."""
    return (RPR_GetExtState(EXT_STATE_SECTION, EXT_STATE_MODEL_KEY) or "").strip()

def set_selected_model(model_id):
    RPR_SetExtState(EXT_STATE_SECTION, EXT_STATE_MODEL_KEY, model_id or "", True)

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

def http_get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'MIDI-GPT-REAPER'})
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read().decode('utf-8'))

def get_server_info(model: str = None) -> dict:
    """GET /info -- checkpoint, capabilities, attributes, resolution for the
    given model id, or the server's active/default model if omitted. Used by
    both the model-type detection below and the dashboard, which caches the
    capabilities to decide which advanced controls (pitch mask, remix,
    streaming) to show."""
    url = f"{get_server_url()}/info"
    if model:
        url += f"?model={urllib.parse.quote(model)}"
    return http_get(url)

def get_available_models() -> dict:
    """GET /models -- {"default_model": <id>, "models": [{"id": ..., "checkpoint": ...}, ...]}.
    Only meaningful once the server has been confirmed reachable -- the
    dashboard's Model dropdown stays hidden until this has succeeded once."""
    return http_get(f"{get_server_url()}/models")

class HttpServerError(Exception):
    """Raised by http_post() on a non-2xx response. str(e) always carries
    the server's parsed "detail" (e.g. the specific validation reason for a
    422), not just the generic HTTP reason phrase -- callers that only keep
    str(e) around (e.g. GenerationHandle.error) still get the real reason."""
    def __init__(self, code, detail):
        self.code = code
        self.detail = detail
        super().__init__(f"HTTP {code}: {detail}")

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
        except Exception:
            detail = e.reason
        print(f"HTTP Server Error {e.code}: {detail}\n")
        raise HttpServerError(e.code, detail) from e

# ---------------------------------------------------------------------------
# Async generation -- runs the (potentially slow, up to minutes) POST
# /generate call on a background thread so REAPER's UI thread (which drives
# the ReaImGui defer loop) never blocks on it. Only plain HTTP/JSON work
# happens on the background thread; every REAPER API call (extraction, MIDI
# write-back) stays on the calling/main thread, since REAPER's API isn't
# thread-safe.
# ---------------------------------------------------------------------------

class GenerationHandle:
    def __init__(self, request_id):
        self.request_id = request_id
        self.lock = threading.Lock()
        self.done = False
        self.status = "running"
        self.response = None
        self.error = None
        self.notes_streamed = 0
        self.cancel_sent = False
        self.stream_mode = False
        self.started_at = time.time()

def _run_stream(server_url, request_dict, handle):
    import urllib.error
    data = json.dumps(request_dict).encode('utf-8')
    req = urllib.request.Request(
        f"{server_url}/generate", data=data,
        headers={'Content-Type': 'application/json', 'User-Agent': 'MIDI-GPT-REAPER'})
    try:
        with urllib.request.urlopen(req, timeout=600) as response:
            for raw_line in response:
                try:
                    line = raw_line.decode('utf-8').strip()
                except Exception:
                    continue
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if not payload:
                    continue
                try:
                    evt = json.loads(payload)
                except Exception:
                    continue
                etype = evt.get("type")
                if etype == "notes":
                    with handle.lock:
                        handle.notes_streamed += len(evt.get("notes", []))
                elif etype in ("done", "cancelled"):
                    with handle.lock:
                        handle.response = evt.get("response")
                        handle.status = (handle.response or {}).get("status", etype)
                        handle.done = True
                    return
                elif etype == "error":
                    with handle.lock:
                        handle.error = evt.get("error", "unknown streaming error")
                        handle.status = "error"
                        handle.done = True
                    return
        with handle.lock:
            if not handle.done:
                handle.error = "Stream ended with no terminal event."
                handle.status = "error"
                handle.done = True
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode('utf-8')
            err_json = json.loads(err_body)
            detail = err_json.get("detail", err_body)
        except Exception:
            detail = e.reason
        with handle.lock:
            handle.error = f"HTTP {e.code}: {detail}"
            handle.status = "error"
            handle.done = True
    except Exception as e:
        with handle.lock:
            handle.error = str(e)
            handle.status = "error"
            handle.done = True

def _run_blocking(server_url, request_dict, handle):
    try:
        response = http_post(f"{server_url}/generate", request_dict)
        with handle.lock:
            handle.response = response
            handle.status = response.get("status", "completed")
            handle.done = True
    except Exception as e:
        with handle.lock:
            handle.error = str(e)
            handle.status = "error"
            handle.done = True

def start_generation(server_url: str, request_dict: dict, use_streaming: bool) -> GenerationHandle:
    """Kicks off POST /generate on a background thread and returns
    immediately with a handle to poll. request_dict is mutated in place to
    carry the client-generated request_id (needed for cancel) and, if
    streaming, stream=True."""
    request_id = request_dict.get("request_id") or uuid.uuid4().hex
    request_dict["request_id"] = request_id
    if use_streaming:
        request_dict["stream"] = True

    handle = GenerationHandle(request_id)
    handle.stream_mode = use_streaming
    target = _run_stream if use_streaming else _run_blocking
    threading.Thread(target=target, args=(server_url, request_dict, handle), daemon=True).start()
    return handle

def cancel_generation(handle: "GenerationHandle | None") -> None:
    """Fires POST /generate/{request_id}/cancel on its own background
    thread (so a slow/unreachable server can't freeze the UI here either).
    Cancellation is cooperative -- the in-flight generation's own thread
    will report status='cancelled' once the server acts on it."""
    if handle is None:
        return
    with handle.lock:
        if handle.done or handle.cancel_sent:
            return
        handle.cancel_sent = True

    server_url = get_server_url()
    request_id = handle.request_id

    def _do_cancel():
        try:
            req = urllib.request.Request(
                f"{server_url}/generate/{request_id}/cancel",
                data=b"{}", method="POST",
                headers={'Content-Type': 'application/json', 'User-Agent': 'MIDI-GPT-REAPER'})
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass

    threading.Thread(target=_do_cancel, daemon=True).start()

# ---------------------------------------------------------------------------
# Global Options
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
        self.num_candidates       = 1

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
            "num_candidates"        : max(1, min(16, int(self.num_candidates))),
        }

        if self.seed >= 0:
            d["seed"] = self.seed
            
        return d

GLOBAL_PARAMS_KEY = "global_params_v1"

def get_global_options() -> GlobalOptions:
    """Read global options saved by REAPER_midigpt_dashboard.py (ReaImGui).
    Returns defaults if the dashboard has never saved anything for this
    project."""
    opts = GlobalOptions()
    ret, _, _, _, value, _ = RPR_GetProjExtState(0, EXT_STATE_SECTION, GLOBAL_PARAMS_KEY, "", 8192)
    if ret <= 0 or not value:
        return opts
    try:
        d = json.loads(value)
    except Exception as e:
        print(f"Error reading dashboard global params: {e}\n")
        return opts

    for field in vars(opts):
        if field in d:
            setattr(opts, field, d[field])
    return opts

TRACK_PARAMS_KEY = "track_params_v1"

def _get_track_params_from_dashboard() -> dict:
    """Read per-track options saved by REAPER_midigpt_dashboard.py, keyed by
    track GUID. Returns {} if the dashboard has never saved anything for
    this project -- callers fall back to defaults for those tracks."""
    ret, _, _, _, value, _ = RPR_GetProjExtState(0, EXT_STATE_SECTION, TRACK_PARAMS_KEY, "", 262144)
    if ret <= 0 or not value:
        return {}
    try:
        return json.loads(value)
    except Exception as e:
        print(f"Error reading dashboard track params: {e}\n")
        return {}

def _get_track_guid(track) -> str:
    return RPR_GetSetMediaTrackInfo_String(track, "GUID", "", False)[3]

def _compute_track_prompt_fields(model_type: str, is_drum_track: bool, v: dict):
    """Shared attrs/bar_attrs/is_ar/is_ignored computation, given a dict of
    raw 0-based values (0 = Any/unset) from the dashboard's per-track
    combo/slider values."""
    attrs = {}
    bar_attrs = {}

    is_ar      = bool(round(v.get("autoregressive", 0)))
    is_ignored = bool(round(v.get("ignore", 0)))

    density   = int(v.get("density", 0))
    min_poly  = int(v.get("min_polyphony_q", 0))
    max_poly  = int(v.get("max_polyphony_q", 0))
    min_dur   = int(v.get("min_note_duration_q", 0))
    max_dur   = int(v.get("max_note_duration_q", 0))

    if model_type == "yellow":
        if density  > 0 and is_drum_track:     attrs["note_density"]      = density - 1
        if min_poly > 0 and not is_drum_track: attrs["min_polyphony"]     = min_poly - 1
        if max_poly > 0 and not is_drum_track: attrs["max_polyphony"]     = max_poly - 1
        if min_dur  > 0 and not is_drum_track: attrs["min_note_duration"] = min_dur - 1
        if max_dur  > 0 and not is_drum_track: attrs["max_note_duration"] = max_dur - 1
        return attrs, bar_attrs, is_ar, is_ignored

    # Prism and Expressive share key_signature/pitch_range/silence_proportion/
    # note_duration (track-level) and density/polyphony/pitch_class_set
    # (bar-level); Expressive additionally has nomml (track-level).
    key_sig   = int(v.get("key_signature", 0))
    pitch_rng = int(v.get("pitch_range", 0))
    silence   = int(v.get("silence_proportion", 0))
    pcs       = int(v.get("pitch_class_set", 0))

    if key_sig   > 0 and not is_drum_track: attrs["key_signature"]      = key_sig - 1
    if pitch_rng > 0 and not is_drum_track: attrs["pitch_range"]        = pitch_rng - 1
    if silence   > 0: attrs["silence_proportion"] = silence - 1
    if min_dur   > 0 and not is_drum_track: attrs["min_note_duration"]  = min_dur - 1
    if max_dur   > 0 and not is_drum_track: attrs["max_note_duration"]  = max_dur - 1

    if density  > 0 and is_drum_track:     bar_attrs["bar_note_density"]  = density - 1
    if min_poly > 0 and not is_drum_track: bar_attrs["bar_min_polyphony"] = min_poly - 1
    if max_poly > 0 and not is_drum_track: bar_attrs["bar_max_polyphony"] = max_poly - 1
    if pcs      > 0 and not is_drum_track: bar_attrs["pitch_class_set"]   = pcs - 1

    if model_type == "expressive":
        nomml = int(v.get("nomml", 0))
        if nomml > 0: attrs["nomml"] = nomml - 1

    return attrs, bar_attrs, is_ar, is_ignored

def _compute_track_controls(v: dict) -> dict:
    """Builds TrackPrompt.controls (pitch_mask / remix) from
    dashboard-saved per-track values. Tracks with no dashboard-saved values
    just get {} (server treats a missing controls sub-field as "off")."""
    controls = {}

    pm_mode = int(v.get("pitch_mask_mode", 0))
    if pm_mode in (1, 2):
        pitch_mask = {}
        if pm_mode == 1:
            pitch_mask["scale"] = v.get("pitch_mask_scale", "major")
            pitch_mask["root"] = int(v.get("pitch_mask_root", 0))
        else:
            bitmask = int(v.get("pitch_mask_classes", 0))
            classes = [pc for pc in range(12) if bitmask & (1 << pc)]
            if classes:
                pitch_mask["pitch_classes"] = classes

        shape_mode = int(v.get("pitch_shape_mode", 0))
        if shape_mode == 1:
            pitch_mask["shape"] = {
                "type": "uniform",
                "min": int(v.get("pitch_shape_min", 48)),
                "max": int(v.get("pitch_shape_max", 72)),
            }
        elif shape_mode == 2:
            pitch_mask["shape"] = {
                "type": "normal",
                "mean": int(v.get("pitch_shape_mean", 60)),
                "std": float(v.get("pitch_shape_std", 8.0)),
            }

        if "scale" in pitch_mask or "pitch_classes" in pitch_mask:
            controls["pitch_mask"] = pitch_mask

    if bool(v.get("remix_enabled", 0)):
        controls["remix"] = {
            "amount": float(v.get("remix_amount", 0.3)),
            "mode": "full" if int(v.get("remix_mode", 0)) == 1 else "pitch",
        }

    return controls

def get_track_prompts(num_measures: int, model_type: str, extraction):
    """
    Read per-track options and attributes for each track, returning a list of
    TrackPrompt dicts matching the structure of midigpt.inference.config.TrackPrompt.
    Values come from REAPER_midigpt_dashboard.py (keyed by track GUID); a
    track the dashboard has never touched just gets defaults.
    """
    tracks_prompts = []
    dashboard_track_params = _get_track_params_from_dashboard()

    for track_info in extraction.song.track_info:
        i = track_info.track_index
        track = track_info.track
        is_drum_track = getattr(track_info, 'instrument', 0) == 128

        guid = _get_track_guid(track)
        v = dashboard_track_params.get(guid, {})
        source = "dashboard" if guid in dashboard_track_params else "default"
        attrs, bar_attrs, is_ar, is_ignored = _compute_track_prompt_fields(
            model_type, is_drum_track, v)
        track_controls = _compute_track_controls(v)

        # Determine target bars to generate
        masked_bars = [b for b in range(num_measures) if extraction.masks.is_masked(i, b)]

        if is_ignored:
            bars_to_gen = []
            is_ar = False
        elif is_ar:
            if masked_bars:
                # AR fires only when at least one item on this track is selected
                bars_to_gen = list(range(num_measures))
            else:
                # AR is toggled but nothing selected on this track -- skip silently
                bars_to_gen = []
                is_ar = False
        else:
            bars_to_gen = masked_bars

        # Apply bar-level attrs to every bar being generated
        per_bar_attributes = (
            {b: dict(bar_attrs) for b in bars_to_gen}
            if bar_attrs and bars_to_gen else {}
        )

        if is_ignored:
            role = "IGNORE"
        elif is_ar:
            role = f"AR (all {num_measures} bars)"
        elif bars_to_gen:
            role = f"INFILL bars={bars_to_gen}"
        else:
            role = "CONTEXT only"
        controls_note = f", controls={json.dumps(track_controls)}" if track_controls else ""
        print(f"  Track {i} ({track_info.track_name}): {role}  [source: {source}, ignore={is_ignored}, autoregressive={is_ar}{controls_note}]\n")

        tracks_prompts.append({
            "id": i,
            "bars": bars_to_gen,
            "autoregressive": is_ar,
            "ignore": is_ignored,
            "mask_bars": [],
            "attributes": attrs,
            "bar_attributes": per_bar_attributes,
            "controls": track_controls,
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

def _redact_score_notes(score_dict: dict) -> dict:
    """Deep-copies score_dict for logging, replacing each bar's note list
    with a placeholder string so the console log shows full request
    structure without dumping every note's pitch/velocity/tick data."""
    redacted = copy.deepcopy(score_dict)
    for track in redacted.get("tracks", []):
        for bar in track.get("bars", []):
            notes = bar.get("notes", [])
            bar["notes"] = f"... ({len(notes)} notes omitted)"
    return redacted

# ---------------------------------------------------------------------------
# Result Write-Back
# ---------------------------------------------------------------------------

def write_generated_score(score_dict: dict, extraction) -> None:
    from midi_extraction import MIDINote, REAPERMIDIWriter

    resolution = score_dict.get("resolution", 12)
    writer = REAPERMIDIWriter(extraction.tempo_map)

    # Precompute which track IDs are autoregressive (only those that actually fire)
    ar_track_ids = {tp["id"] for tp in extraction.track_prompts if tp.get("autoregressive")}

    resp_tracks = score_dict.get("tracks", [])
    if len(resp_tracks) != extraction.song.num_tracks:
        print(f"WARNING: Response has {len(resp_tracks)} tracks but extraction has {extraction.song.num_tracks}.\n")

    for track_idx, track_data in enumerate(resp_tracks):
        track_info = extraction.song.get_track_info(track_idx)
        if not track_info:
            continue

        for bar_idx, bar_data in enumerate(track_data.get("bars", [])):
            # Only write back generated bars (masked or autoregressive)
            if not extraction.masks.is_masked(track_idx, bar_idx):
                if track_idx not in ar_track_ids:
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

def prepare_generation():
    """Everything through building the POST /generate payload: server info,
    Global/Track Options, MIDI extraction, and Score serialization. All
    REAPER-API work, plus one small GET /info call -- safe to run on the
    main thread. Returns a context dict on success (having already printed
    progress to the console), or None (having already printed why) on
    failure. Does NOT touch POST /generate itself -- that's the slow call,
    handed off to start_generation() on a background thread."""
    RPR_ClearConsole()

    server_url = get_server_url()
    selected_model = get_selected_model()

    print(f"Connecting to MIDI-GPT HTTP server at {server_url}...\n")
    try:
        info_url = f"{server_url}/info"
        if selected_model:
            info_url += f"?model={urllib.parse.quote(selected_model)}"
        info = http_get(info_url)
    except Exception as e:
        print(f"Cannot reach server at {server_url}:\n  {e}\n")
        print("Please make sure the MIDI-GPT server is running and reachable, and that")
        print("the server address is correct (MIDI-GPT: Set server address action).\n")
        return None

    checkpoint = info.get("checkpoint", "unknown")
    capabilities = info.get("capabilities", {})
    attributes = info.get("attributes", {})
    resolution = info.get("resolution", 12)

    if "nomml" in attributes:
        model_type = "expressive"
    elif "key_signature" in attributes:
        model_type = "prism"
    else:
        model_type = "yellow"

    print(f"Active Checkpoint : {checkpoint}")
    print(f"Requested Model   : {selected_model or '(server default)'}")
    print(f"Model Type        : {model_type.upper()}")
    print(f"Tick Resolution   : {resolution}")
    print(f"Masking Support   : pitch_mask={capabilities.get('supports_pitch_mask', False)}, "
          f"remix={capabilities.get('supports_remix', False)}, "
          f"streaming={capabilities.get('supports_streaming', False)}\n")

    options = get_global_options()
    print("Global options loaded.")

    print("Extracting MIDI from REAPER...\n")
    try:
        extraction = extract_midi_for_mmm(
            mask_selected_items=True,
            mask_empty_items=False,
        )
    except Exception:
        print(f"Extraction failed:\n{traceback.format_exc()}\n")
        return None

    num_measures = extraction.song.num_measures
    if num_measures == 0:
        print("No MIDI found in selection.\n")
        return None
    if extraction.masks.count == 0:
        print("No measures to infill -- select some MIDI items first.\n")
        return None

    print(f"Tracks   : {extraction.song.num_tracks}")
    print(f"Measures : {extraction.start_measure}-{extraction.end_measure}")
    print(f"Masked   : {extraction.masks.count} (track, bar) positions\n")

    print("Track roles:")
    track_prompts = get_track_prompts(num_measures, model_type, extraction)
    # Stash prompts in extraction result for write-back filtering
    extraction.track_prompts = track_prompts

    ar_tracks = [tp["id"] for tp in track_prompts if tp["autoregressive"]]
    if ar_tracks:
        print(f"\nWARNING: Track(s) {ar_tracks} have Autoregressive ON.")
        print("All bars in those tracks will regenerate regardless of selection.\n")
    else:
        print()

    print("Converting MIDI data...")
    score_dict = song_to_score_dict(extraction.song, resolution)

    config = options.to_config_dict(capabilities.get("supports_token_mask", False))

    if any(tp.get("controls", {}).get("remix") for tp in track_prompts) and config.get("tracks_per_step", 1) != 1:
        print("Remix is active on at least one track -- forcing tracks_per_step=1 "
              "for this request (remix requires it).\n")
        config["tracks_per_step"] = 1

    request_dict = {
        "score": score_dict,
        "request": {
            "tracks": track_prompts,
            "config": config,
        },
    }
    if selected_model:
        request_dict["model"] = selected_model

    # Full outgoing request -- lets you check the exact JSON the server
    # receives, e.g. to confirm a pitch mask or remix control actually made
    # it into the payload instead of guessing from the summary line above.
    # request.score's per-bar note lists are redacted to a count (they're
    # the bulk of the payload and not useful to eyeball) -- everything else
    # in the score, and all of request.tracks/config, is printed in full.
    print("Outgoing request.score (notes omitted):")
    print(json.dumps(_redact_score_notes(score_dict), indent=2) + "\n")
    print("Outgoing request.tracks:")
    print(json.dumps(track_prompts, indent=2) + "\n")
    print(f"Outgoing request.config: {json.dumps(config)}\n")

    return {
        "server_url": server_url,
        "model_type": model_type,
        "capabilities": capabilities,
        "resolution": resolution,
        "extraction": extraction,
        "request_dict": request_dict,
    }

def finish_generation(handle: GenerationHandle, ctx: dict):
    """Call once handle.done is True. Writes the generated score back into
    REAPER (main-thread REAPER API calls) and returns a result dict --
    {"seed", "tokens", "elapsed", "status", "candidates", "selected_index",
    "extraction"} -- or None on failure. "candidates" is None for an
    ordinary num_candidates=1 response, or a list of per-candidate dicts
    (index/seed/gen_count/error/truncated/score) when the server used the
    batch response shape; "selected_index" is whichever candidate got
    written back (the first successful one)."""
    with handle.lock:
        status = handle.status
        error = handle.error
        response = handle.response

    elapsed = time.time() - handle.started_at
    extraction = ctx["extraction"]

    if error:
        print(f"\nGeneration request failed: {error}\n")
        return None

    if response is None:
        print("\nGeneration ended with no response (likely cancelled before anything was generated).\n")
        return None

    if status == "cancelled":
        print("\nGeneration was cancelled" + (" -- writing back whatever was generated so far.\n" if response.get("score") or response.get("candidates") else ".\n"))

    tokens = response.get("tokens", {}) or {}

    if "candidates" in response:
        candidates_raw = response.get("candidates", [])
        summary = response.get("summary", {})
        base_seed = response.get("base_seed")
        print(f"Batch generation finished in {elapsed:.2f}s -- "
              f"{summary.get('succeeded', 0)}/{summary.get('requested', len(candidates_raw))} candidate(s) succeeded.\n")
        for f in summary.get("failures", []):
            print(f"  Candidate seed {f.get('seed')} failed: {f.get('reason')}\n")
        if base_seed is not None:
            print(f"Base seed: {base_seed}\n")

        candidates = []
        selected_index = None
        for i, c in enumerate(candidates_raw):
            ok = c.get("score") is not None and not c.get("error")
            candidates.append({
                "index": i, "seed": c.get("seed"), "gen_count": c.get("gen_count"),
                "error": c.get("error"), "truncated": bool(c.get("truncated")),
                "score": c.get("score"),
            })
            if ok and selected_index is None:
                selected_index = i

        if selected_index is None:
            print("All candidates failed -- nothing written back.\n")
            return {
                "seed": base_seed, "tokens": tokens, "elapsed": elapsed, "status": status,
                "candidates": candidates, "selected_index": None, "extraction": extraction,
            }

        print(f"Writing candidate {selected_index + 1} (seed {candidates[selected_index]['seed']}) to REAPER...\n")
        try:
            write_generated_score(candidates[selected_index]["score"], extraction)
        except Exception:
            print(f"Write-back failed:\n{traceback.format_exc()}\n")
            return None

        print("Done. Use the batch buttons to swap between candidates before generating again.\n")
        RPR_Undo_OnStateChange("MIDI-GPT Infill (batch)")
        return {
            "seed": candidates[selected_index]["seed"], "tokens": tokens, "elapsed": elapsed, "status": status,
            "candidates": candidates, "selected_index": selected_index, "extraction": extraction,
        }

    # ---- Single-candidate response shape ---------------------------------- #
    if not response.get("score"):
        print(f"\nServer error or empty result: {response.get('detail', 'no score in response')}\n")
        return None

    seed = response.get("seed")
    print(f"Generation completed in {elapsed:.2f}s (status: {status}).\n")
    if seed is not None:
        print(f"Seed: {seed}\n")
    if tokens:
        ctx_tok = tokens.get("context_tokens")
        gen_tok = tokens.get("generated_tokens")
        max_tok = tokens.get("max_context_tokens")
        util = tokens.get("context_utilization")
        tps = tokens.get("tokens_per_second")
        if ctx_tok is not None and gen_tok is not None and max_tok is not None:
            print(f"Tokens: {ctx_tok} context + {gen_tok} generated / {max_tok} max"
                  + (f" ({util * 100:.0f}%)" if util is not None else "") + "\n")
        if tps is not None:
            print(f"Speed: {tps:.1f} tokens/sec\n")
        if tokens.get("truncated"):
            print("WARNING: generation was truncated -- hit the context ceiling before finishing (may be cut off mid-bar).\n")

    print("Writing generated MIDI to REAPER...\n")
    try:
        write_generated_score(response["score"], extraction)
    except Exception:
        print(f"Write-back failed:\n{traceback.format_exc()}\n")
        return None

    print("Done.\n")
    RPR_Undo_OnStateChange("MIDI-GPT Infill")

    return {
        "seed": seed, "tokens": tokens, "elapsed": elapsed, "status": status,
        "candidates": None, "selected_index": None, "extraction": extraction,
    }

# request_id -> (handle, ctx) for every standalone "MIDI-GPT: Run infill"
# invocation still in flight. Keyed rather than a single shared global/
# closure -- with just one shared slot, triggering this action again before
# a prior run finished would silently overwrite it, orphaning the first
# handle/ctx (its result never gets polled, written back, or reported; it
# just vanishes with no error). Keying by request_id lets any number of
# concurrent standalone runs coexist safely.
_infill_poll_handles = {}

def _infill_poll_dispatch():
    """Single stable RPR_defer target -- ticks every in-flight standalone
    run each cycle and reschedules itself as long as any are still pending."""
    for request_id, (handle, ctx) in list(_infill_poll_handles.items()):
        with handle.lock:
            done = handle.done
        if done:
            del _infill_poll_handles[request_id]
            finish_generation(handle, ctx)
    if _infill_poll_handles:
        RPR_defer("_infill_poll_dispatch()")

def run_midigpt_infill():
    """Standalone (Action List) entry point. Kicks off preparation +
    generation and keeps itself alive via RPR_defer to poll for completion
    -- like the dashboard's own loop, this never blocks REAPER's UI thread
    on the network call. Always returns None immediately; the actual result
    is printed to the console once generation finishes. Safe to trigger
    again before a prior run finishes -- see _infill_poll_handles above."""
    ctx = prepare_generation()
    if ctx is None:
        return None

    capabilities = ctx["capabilities"]
    num_candidates = ctx["request_dict"]["request"]["config"].get("num_candidates", 1)
    use_streaming = bool(capabilities.get("supports_streaming")) and num_candidates == 1

    print("Generating MIDI via MIDI-GPT HTTP server"
          + (" (streaming)" if use_streaming else " (this may take a while)") + "...\n")
    handle = start_generation(ctx["server_url"], ctx["request_dict"], use_streaming)

    was_idle = not _infill_poll_handles
    _infill_poll_handles[handle.request_id] = (handle, ctx)
    if was_idle:
        RPR_defer("_infill_poll_dispatch()")
    return None

if __name__ == "__main__":
    run_midigpt_infill()
