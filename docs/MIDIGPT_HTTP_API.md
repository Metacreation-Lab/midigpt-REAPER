# midigpt-http API

Reference for the stateless `midigpt` HTTP server (the pip-installed `midigpt`
package's built-in server, `python -m midigpt.http.server` / `midigpt-http`
console script), default port 8000. Every request is fully self-contained —
the server holds no per-session state, only the loaded model and a semaphore
that serializes work (single model, one generation in flight at a time).

There is a separate stateful `session_relay` service (this repo,
`session_relay/`, port 8100) for multi-user collaborative sessions — that's a
distinct layer in front of this one. This document covers midigpt-http only.

---

## `GET /health`
Liveness probe, also resets the idle-shutdown timer. Returns:
```json
{"status": "ok"}
```

## `GET /info`
```json
{
  "checkpoint": "yellow_medium",
  "capabilities": {
    "tension": true, "note_density": true,
    "min_polyphony": true, "max_polyphony": true,
    "min_note_duration": true, "max_note_duration": true,
    "supports_token_mask": true,
    "supports_attention_mask": true, "supports_attention_approx": true, "supports_attention_skip": true,
    "supports_remove": true,
    "supports_pitch_mask": true,
    "pitch_mask_scale_presets": ["blues", "chromatic", "dorian", "..."],
    "supports_rhythm_mask": true,
    "rhythm_mask_grid_units": ["eighth", "eighth_triplet", "half", "..."],
    "supports_remix": true,
    "supports_streaming": true
  },
  "attributes": { "note_density": 8, "tension": 4 },
  "resolution": 12
}
```
`capabilities.*` fields tell the frontend what's available for a given loaded
checkpoint — check `supports_pitch_mask`/`supports_rhythm_mask`/
`supports_remix` before offering those controls in the UI, since they depend
on the checkpoint's token grammar. `resolution` is ticks-per-quarter-note for
that checkpoint — needed if the client wants to convert its own tick units
into `rhythm_mask.positions` pos values.

---

## `POST /generate`

### Request body
```jsonc
{
  "score": { /* Score.to_dict() shape — tracks, bars, notes */ },
  "request": { /* GenerationRequest, see below */ },
  "request_id": "optional-caller-supplied-string",   // omit to let the server generate a uuid4 hex
  "stream": false                                     // true = SSE streaming response, see below
}
```

**`request_id`** — same idea as the request-id convention on LLM APIs. If you
omit it, the server generates one and returns it both in the response body
and in the `X-Request-Id` response header. You need it to call the cancel
endpoint on this specific in-flight generation; it's also useful purely for
log correlation. Supply your own if you want end-to-end idempotency/
correlation with your own system.

**`stream`** — `false` (default): ordinary single JSON response, unchanged
from before. `true`: `text/event-stream` response — see **Streaming** below.
Streaming is opt-in; the non-streaming call path is fully preserved for
clients that don't need it.

### `request` (GenerationRequest)
```jsonc
{
  "tracks": [ /* list of TrackPrompt, see below */ ],
  "config": { /* InferenceConfig, see below */ },
  "controls": {
    "velocity": true,       // use velocity tokens (requires switchable_velocity in encoder config)
    "microtiming": true,    // use delta/microtiming tokens (requires switchable_microtiming)
    "genre": "jazz"         // canonical genre label (requires genre_groups in encoder config)
  }
}
```

### `TrackPrompt` (one per entry in `tracks`)
```jsonc
{
  "id": 0,
  "bars": [4, 5, 6, 7],          // bars to GENERATE (AR targets if autoregressive=true, else infill targets)
  "autoregressive": false,
  "ignore": false,
  "mask_bars": [],                // bars to hide from the model entirely (disjoint from `bars`)
  "attributes": {"note_density": 3},   // analyzer-derived attribute conditioning, per-track
  "controls": {
    "time_signature": 0,          // index into encoder_config.time_signatures
    "pitch_mask": { /* see below */ },
    "rhythm_mask": { /* see below */ },
    "remix": { /* see below */ }
  },
  "bar_attributes": { "4": {"note_density": 2} },   // per-bar attribute overrides, keyed by absolute bar index
  "bar_controls":   { "4": {"pitch_mask": {}} }     // per-bar control overrides
}
```
Any bar in the step window that's not in `bars` or `mask_bars` becomes context
(the actual existing notes on `score`, including silence if the bar is
empty). Bars not in `bars` don't get regenerated.

#### `controls.pitch_mask`
Restricts/shapes which pitches this track's note-onset tokens may sample.
All-optional; combine a hard allow-set with an optional soft `shape` layered
on top.

Hard allow-set (pick **one**):
```jsonc
{"pitches": [60, 62, 64, 65, 67, 69, 71]}          // exact MIDI pitch allow-list
{"scale": "major", "root": 0}                       // preset scale, root = pitch class 0-11 (C=0)
{"pitch_classes": [0, 2, 4, 5, 7, 9, 11]}           // any pitch class, any octave
```
Scale presets (`GET /info` → `capabilities.pitch_mask_scale_presets`):
`chromatic, major, natural_minor, harmonic_minor, melodic_minor, dorian,
phrygian, lydian, mixolydian, locrian, major_pentatonic, minor_pentatonic,
blues, whole_tone`.

Soft reweight, optional, layered on top of the hard set (multiply into
post-softmax probs + renormalize — never zeroes out anything the hard mask
already allowed, except `uniform` clipping):
```jsonc
"shape": {"type": "uniform", "min": 48, "max": 72}   // flat weight inside [min,max], 0 outside — a soft register clamp
"shape": {"type": "normal", "mean": 60, "std": 8}     // gaussian centered on mean — soft register preference, never fully zero
```

#### `controls.rhythm_mask`
Restricts/shapes which within-bar tick this track's rhythm-position tokens
may land on. `positions` (hard) and `grid` (soft) are **mutually
exclusive**.

Hard exact rhythm — forces the note-onset grid exactly, including
per-position polyphony. **Requires `config.tracks_per_step == 1`.**
```jsonc
"positions": [
  {"pos": 0, "polyphony": 1},
  {"pos": 24, "polyphony": 2}
]
```
`pos` = tick within the bar (checkpoint's resolution — see `GET /info` →
`resolution`). The **first entry must be `pos: 0`** — every bar opens with an
implicit note at tick 0, there's no token for leading silence.

Soft grid-granularity bias (multiply into the position sub-distribution +
renormalize):
```jsonc
"grid": {"unit": "eighth", "strength": 0.8}
```
`unit` ∈ `whole, half, quarter, eighth, sixteenth, quarter_triplet,
eighth_triplet, sixteenth_triplet` (`GET /info` →
`capabilities.rhythm_mask_grid_units`). `strength` ∈ [0,1]: 1.0 hard-quantizes
to that grid (off-grid ticks get weight 0), 0.0 is a no-op.

#### `controls.remix`
Regenerates this track's bars as a partial variation of the content
**already present on `score`** for those bars, instead of generating fresh.
The onset schedule (which ticks have notes, how many per tick) is always
reproduced exactly from the reference — only note-level values are eligible
for resampling.
```jsonc
{"amount": 0.3, "mode": "pitch"}
```
- `amount` ∈ [0, 1] — fraction of eligible note-attributes resampled. `0.0`
  reproduces the reference exactly; `1.0` resamples every eligible attribute.
- `mode: "pitch"` — only pitch is ever eligible; duration always kept exact
  ("vary the notes, keep the rhythm").
- `mode: "full"` — pitch and duration are each independently eligible.
- Velocity is always left to free sampling in both modes (no raw-velocity
  quantizer to force it against reference).
- Mutually exclusive with `rhythm_mask` on the same track (remix derives its
  own schedule from the reference).
- Requires `config.tracks_per_step == 1`, same reasoning as
  `rhythm_mask.positions`.

### `config` (InferenceConfig)
```jsonc
{
  "temperature": 1.0,
  "seed": -1,                     // -1 = pick a random seed each call (not "reuse -1 literally")
  "max_attempts": 3,
  "novelty_check": true,
  "silence_check": true,
  "temperature_escalation": 1.0,
  "bars_per_step": 1,
  "tracks_per_step": 1,
  "model_dim": 4,
  "shuffle": false,
  "mask_mode": "token",           // "token" | "attention" | "attention_approx" | "attention_skip" | "remove"
  "polyphony_hard_limit": 0,      // 0 = no cap
  "density_hard_limit": 0,        // 0 = no cap
  "top_p": 1.0,
  "top_k": 0,
  "mask_p": 0.0,
  "mask_k": 0,
  "batch_attempts": false,
  "num_candidates": 1             // >1 routes through the "candidates" response shape below
}
```

### Response — non-streaming, `num_candidates == 1` (default)
```jsonc
{
  "request_id": "…",
  "status": "completed",           // or "cancelled" if a cancel request landed mid-generation
  "score": { /* full Score.to_dict() */ },   // null only if cancelled before anything usable was generated
  "seed": 12345,
  "timing": {
    "model_forward_s": 1.83, "encode_s": 0.02, "decode_s": 0.01, "gen_count": 214
  },
  "tokens": {
    "context_tokens": 512, "generated_tokens": 214, "max_context_tokens": 2048,
    "context_utilization": 0.25, "tokens_per_second": 116.9,
    "truncated": false             // true = generation hit the context budget, not a natural grammar end
  }
}
```
`X-Request-Id` header is also set on the response.

### Response — non-streaming, `num_candidates > 1`
```jsonc
{
  "request_id": "…",
  "status": "completed",
  "base_seed": 12345,
  "candidates": [
    {"score": {}, "seed": 12345, "gen_count": 214, "error": null, "truncated": false},
    {"score": {}, "seed": 12346, "gen_count": 198, "error": null, "truncated": false}
  ],
  "summary": {"requested": 2, "succeeded": 2, "failed": 0, "failures": []},
  "timing": {},
  "tokens": {}
}
```

### Errors
- `400` — malformed `score`/`request` body (KeyError/TypeError/ValueError while parsing)
- `422` — structurally valid but semantically invalid request
  (`RequestValidationError` — e.g. bad `pitch_mask`/`rhythm_mask`/`remix`
  shape, unknown scale name, `positions` schedule not starting at 0,
  `rhythm_mask`+`remix` both set on the same track, `tracks_per_step != 1`
  with a hard `rhythm_mask.positions`/`remix`, etc.)
- `500` — inference failure; the failing request+error is also appended to a
  JSONL log for offline debugging

---

## Streaming (`stream: true`)

Response is `text/event-stream`, `X-Request-Id` header set immediately. Each
frame:
```
data: {...json...}\n\n
```

Event types, in order — zero or more `"notes"` events, then exactly one of
`"done"` / `"cancelled"` / `"error"`:

**`notes`** — fired as soon as each note finishes decoding (streamed live,
not batched by bar):
```json
{"type": "notes", "notes": [{"track": 0, "bar": 4, "pitch": 60, "onset_tick": 0, "duration_tick": 24, "velocity": 90}]}
```

**`done`** — normal completion:
```json
{"type": "done", "response": { "...same shape as the non-streaming single response above, status: completed..." }}
```

**`cancelled`** — a cancel request landed mid-generation:
```json
{"type": "cancelled", "response": { "...same response shape, status: cancelled, score = whatever was generated so far..." }}
```

**`error`**:
```json
{"type": "error", "request_id": "…", "error": "message"}
```

Notes:
- **Not yet supported together with `num_candidates > 1`** — that request
  returns `400` (each candidate would need its stream events tagged by
  candidate index; not implemented).
- Client disconnect mid-stream is handled server-side: the background
  generation is force-stopped and the request's slot in the semaphore is
  released only after it's confirmed finished — a dropped connection can't
  leave a zombie generation blocking the (single-model) server.

---

## `POST /generate/{request_id}/cancel`
Requests cancellation of an in-flight generation by its `request_id` (the one
echoed back from the original `/generate` call, streaming or not).
```json
{"request_id": "…", "status": "cancelling"}
```
`404` if there's no in-flight request with that id (already finished, already
cancelled, or never existed). Cancellation is cooperative — it takes effect
at the next token-step boundary, so the generation returns *partial* results
(via the `cancelled` event for streaming, or `status: "cancelled"` in the
JSON body for non-streaming) rather than nothing.
