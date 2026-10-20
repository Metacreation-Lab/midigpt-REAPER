"""Dashboard persistence and REAPER/backend actions."""

import json
import copy
import importlib

from reaper_python import *

# The sibling REAPER action scripts have spaces in their filenames (e.g.
# "MIDI-GPT Generate.py"), which isn't valid `import` statement syntax --
# importlib.import_module() takes the literal string instead, resolved via
# the same path-based finder REAPER puts this script's own directory on.
infill = importlib.import_module("MIDI-GPT Generate")
setup_tracks = importlib.import_module("MIDI-GPT Setup Tracks")

from . import notify, setup_panel

EXT_STATE_SECTION = "MIDI-GPT"
GLOBAL_PARAMS_KEY = "global_params_v1"
TRACK_PARAMS_KEY = "track_params_v1"

GLOBAL_KEYS = {
    "temperature", "model_dim", "bars_per_step", "tracks_per_step",
    "polyphony_hard_limit", "density_hard_limit", "max_attempts",
    "temp_escalation", "top_p", "top_k", "mask_p", "mask_k", "seed",
    "checks_idx", "shuffle", "num_candidates",
}


def _load_json(key, size, default):
    ret, _, _, _, value, _ = RPR_GetProjExtState(0, EXT_STATE_SECTION, key, "", size)
    if ret <= 0 or not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


class DashboardLogic:
    def __init__(self, global_settings, dashboard_state, log_lines):
        self.global_settings = global_settings
        self.dashboard_state = dashboard_state
        self.log_lines = log_lines
        self.active_generation = None
        self.last_generation_result = None
        self.active_batch = None
        self.server_capabilities = {}
        self.model_type = "yellow"
        self.available_models = []
        self.selected_model = ""
        self._last_saved_global = None
        self._last_saved_tracks = None
        self.load_state()

    def refresh_model_info(self):
        """Refresh /info capabilities and /models from the configured server."""
        self.selected_model = infill.get_selected_model()
        try:
            info = infill.get_server_info(self.selected_model or None)
            self.server_capabilities = info.get("capabilities", {})
            attributes = info.get("attributes", {})
            if "nomml" in attributes:
                self.model_type = "expressive"
            elif "key_signature" in attributes:
                self.model_type = "prism"
            else:
                self.model_type = "yellow"
            print(f"Active model: {self.model_type.upper()}\n")
        except Exception as error:
            print(f"Could not query server info: {error}\n")
        try:
            models_info = infill.get_available_models()
            self.available_models = [model["id"] for model in models_info.get("models", []) if model.get("id")]
            default_model = models_info.get("default_model", "")
            if not self.selected_model and default_model:
                self.selected_model = default_model
                infill.set_selected_model(default_model)
            print(f"Available models: {', '.join(self.available_models) or '(none)'}\n")
        except Exception as error:
            self.available_models = []
            print(f"Could not query available models: {error}\n")
            print(setup_panel.server_down_help(self.server_url()) + "\n")

    def load_state(self):
        saved_global = _load_json(GLOBAL_PARAMS_KEY, 8192, {})
        for key in GLOBAL_KEYS:
            if key in saved_global:
                self.global_settings[key] = saved_global[key]
        saved_tracks = _load_json(TRACK_PARAMS_KEY, 262144, {})
        self.dashboard_state.track_settings.update(saved_tracks)
        self._last_saved_global = self._serialized_global()
        self._last_saved_tracks = copy.deepcopy(self._serialized_tracks())

    def server_url(self):
        return infill.get_server_url()

    def _serialized_global(self):
        values = {key: self.global_settings[key] for key in GLOBAL_KEYS}
        values["polyphony_hard_limit"] = values["polyphony_hard_limit"] if self.global_settings.get("polyphony_limit_enabled") else 0
        values["density_hard_limit"] = values["density_hard_limit"] if self.global_settings.get("density_limit_enabled") else 0
        values["temp_escalation"] = values["temp_escalation"] if self.global_settings.get("temp_escalation_enabled") else 1.0
        values["top_p"] = values["top_p"] if self.global_settings.get("top_p_enabled") else 1.0
        values["top_k"] = values["top_k"] if self.global_settings.get("top_k_enabled") else 0
        values["mask_p"] = values["mask_p"] if self.global_settings.get("mask_p_enabled") else 0.0
        values["mask_k"] = values["mask_k"] if self.global_settings.get("mask_k_enabled") else 0
        values["seed"] = values["seed"] if self.global_settings.get("manual_seed") else -1
        return values

    def _serialized_tracks(self):
        return self.dashboard_state.track_settings

    def persist_if_changed(self):
        global_values = self._serialized_global()
        track_values = self._serialized_tracks()
        if global_values != self._last_saved_global:
            RPR_SetProjExtState(0, EXT_STATE_SECTION, GLOBAL_PARAMS_KEY, json.dumps(global_values))
            self._last_saved_global = global_values
        if track_values != self._last_saved_tracks:
            RPR_SetProjExtState(0, EXT_STATE_SECTION, TRACK_PARAMS_KEY, json.dumps(track_values))
            self._last_saved_tracks = copy.deepcopy(track_values)

    def start_generation(self):
        self.persist_if_changed()
        if self.active_generation is not None:
            print("A generation is already running -- wait for it to finish or cancel it.\n")
            return
        context = infill.prepare_generation()
        if context is None:
            notify.error(infill.last_error() or "Couldn't start generation -- see the Console tab for details.")
            return
        for warning_text in context.get("warnings", []):
            notify.warning(warning_text)
        request_config = context["request_dict"]["request"]["config"]
        use_streaming = bool(self.server_capabilities.get("supports_streaming")) and request_config.get("num_candidates", 1) == 1
        handle = infill.start_generation(context["server_url"], context["request_dict"], use_streaming)
        self.active_generation = {"handle": handle, "context": context}
        self.active_batch = None
        # Drop the previous batch's candidates so the picker resets to "no
        # batch yet" for the duration of this request. active_batch alone
        # already blocks switch_candidate() from acting on a stale pick, but
        # last_generation_result -- which the UI reads for the candidate
        # row -- otherwise keeps showing the old (now-irrelevant) buttons
        # as if they still belonged to what's in flight.
        if self.last_generation_result is not None:
            self.last_generation_result = {
                **self.last_generation_result, "candidates": None, "selected_index": None,
            }
        print("Generation started.\n")

    def poll_generation(self):
        if self.active_generation is None:
            return
        handle = self.active_generation["handle"]
        with handle.lock:
            done = handle.done
        if not done:
            return
        active = self.active_generation
        self.active_generation = None
        try:
            result = infill.finish_generation(handle, active["context"])
        except Exception as error:
            print(f"Generation failed: {error}\n")
            notify.error(f"Generation failed: {error}")
            return
        if result is None:
            # Already printed the specific reason (server error, write-back
            # failure, ...) -- don't also wipe last_generation_result, which
            # would blank out a previous successful run's Seed/Time/tokens
            # display for no reason.
            notify.error(infill.last_error() or "Generation failed -- see the Console tab for details.")
            return
        self.last_generation_result = result
        if result.get("candidates") is not None:
            self.active_batch = {
                "candidates": result["candidates"],
                "selected": result.get("selected_index"),
                "context": active["context"],
            }
            if result.get("selected_index") is None:
                # Not a hard failure (result isn't None -- there's still a
                # batch of failed-candidate buttons to show), but nothing
                # got written back, which is worth a popup same as any
                # other failure.
                notify.error(infill.last_error() or "All candidates failed -- nothing written back.")
        tokens = result.get("tokens") or {}
        if result.get("candidates") is None and tokens.get("truncated"):
            notify.warning("Generation was truncated -- it hit the context limit before "
                            "finishing (may be cut off mid-bar).")
        print("Generation finished.\n")

    def cancel_generation(self):
        if self.active_generation is not None:
            infill.cancel_generation(self.active_generation["handle"])
            print("Cancellation requested.\n")

    def switch_candidate(self, index):
        if not self.active_batch:
            return
        candidates = self.active_batch["candidates"]
        if not 0 <= index < len(candidates) or candidates[index].get("score") is None:
            return
        infill.write_generated_score(candidates[index]["score"], self.active_batch["context"]["extraction"])
        self.active_batch["selected"] = index

    def information(self):
        result = self.last_generation_result or {}
        # Prefer the in-flight request's extraction, but fall back to the
        # last completed one so "Bars"/"Tracks" stay put next to the rest of
        # the last-result info instead of disappearing the instant
        # poll_generation() clears active_generation.
        if self.active_generation is not None:
            extraction = self.active_generation["context"].get("extraction")
        else:
            extraction = result.get("extraction")
        track_prompts = getattr(extraction, "track_prompts", None) if extraction is not None else None
        if track_prompts:
            # extraction.masks only reflects the raw selection -- it
            # doesn't know that an autoregressive track expands to every
            # bar in the window regardless of what's selected on it (see
            # get_track_prompts() in MIDI-GPT Generate.py, which
            # already resolves that expansion into each prompt's "bars").
            # Reading it from there instead keeps this honest: 1 bar
            # selected on an AR track reports as however many bars are
            # actually in the request, not as "1".
            generated_bars = len({bar for tp in track_prompts for bar in tp["bars"]})
            generated_tracks = len({tp["id"] for tp in track_prompts if tp["bars"]})
        elif extraction is not None:
            # Fallback in case track_prompts somehow isn't there yet --
            # shouldn't happen in the normal flow (prepare_generation()
            # sets it before a request is ever in flight), but degrades to
            # the old (AR-blind) raw-selection count rather than crashing.
            masked_positions = extraction.masks.to_list()
            generated_bars = len({measure_idx for _, measure_idx in masked_positions})
            generated_tracks = len({track_idx for track_idx, _ in masked_positions})
        else:
            generated_bars = None
            generated_tracks = None

        candidates = result.get("candidates") or []
        selected_index = self.active_batch.get("selected") if self.active_batch else result.get("selected_index")
        # Whichever candidate is currently selected/written -- not just
        # whichever the batch response auto-picked at generation time -- so
        # Seed (and gen_count, below) track the candidate buttons instead of
        # staying frozen on the first one.
        active_candidate = None
        if candidates and selected_index is not None and 0 <= selected_index < len(candidates):
            active_candidate = candidates[selected_index]

        return {
            "model": self.selected_model or "server default",
            "model_type": self.model_type,
            "generated_bars": generated_bars,
            "generated_tracks": generated_tracks,
            "status": result.get("status"),
            "seed": active_candidate["seed"] if active_candidate else result.get("seed"),
            "elapsed": result.get("elapsed"),
            "tokens": result.get("tokens") or {},
            # The server's batch response doesn't include a per-candidate
            # context/max-context breakdown (see docs/MIDIGPT_HTTP_API.md),
            # only gen_count -- so that's the only per-candidate token stat
            # console_panel.py can actually show.
            "candidate_gen_count": active_candidate.get("gen_count") if active_candidate else None,
            "candidates": candidates,
            "selected_candidate": selected_index,
        }

    def run_action(self, action):
        if action == "generate":
            self.start_generation()
        elif action == "cancel":
            self.cancel_generation()
        elif action and action.startswith("batch_select_"):
            self.switch_candidate(int(action[len("batch_select_"):]))
        elif action == "run_track_setup":
            options = setup_panel.get_pending_track_setup()
            setup_tracks.apply_track_setup(
                options["tracks"], options["instruments"], options["name_only"], options["replace_existing"],
            )
        elif action == "refresh_model":
            self.refresh_model_info()
        elif action == "reset":
            self.global_settings.clear()
            self.global_settings.update({
                "temperature": 1.0, "model_dim": 4, "bars_per_step": 1,
                "tracks_per_step": 1, "polyphony_hard_limit": 0,
                "density_hard_limit": 0, "max_attempts": 3,
                "temp_escalation": 1.0, "top_p": 1.0, "top_k": 0,
                "mask_p": 0.0, "mask_k": 0, "seed": -1,
                "checks_idx": 3, "shuffle": 0, "num_candidates": 1,
                "manual_seed": False,
                "polyphony_limit_enabled": False,
                "density_limit_enabled": False,
                "temp_escalation_enabled": False,
                "top_p_enabled": False,
                "top_k_enabled": False,
                "mask_p_enabled": False,
                "mask_k_enabled": False,
            })
            self.dashboard_state.track_settings.clear()
            self.persist_if_changed()
