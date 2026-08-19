[![Metacreation Lab](https://drive.google.com/uc?export=view&id=1nzeq0DmD7hAYteRs5PA42150HIzO3Sz7)](https://metacreation.net/category/projects/)

# MIDI-GPT for REAPER

[![License: MIT](https://img.shields.io/github/license/Metacreation-Lab/midigpt-REAPER)](LICENSE)
[![REAPER](https://img.shields.io/badge/REAPER-v6%2B-5C2D91)](https://www.reaper.fm/)
[![Python](https://img.shields.io/badge/python-3.10--3.12-3776ab)](https://www.python.org/downloads/)
[![Powered by MIDI-GPT](https://img.shields.io/badge/powered%20by-MIDI--GPT-eb1c3b)](https://github.com/Metacreation-Lab/MIDI-GPT)
[![arXiv](https://img.shields.io/badge/arXiv-2501.17011-b31b1b)](https://arxiv.org/abs/2501.17011)
[![HuggingFace](https://img.shields.io/badge/HuggingFace-Metacreation%2FMIDI--GPT-FFD21E?logo=huggingface&logoColor=000)](https://huggingface.co/Metacreation/MIDI-GPT)

AI-powered multi-track MIDI generation plugin for [REAPER](https://www.reaper.fm/), built on the [MIDI-GPT](https://github.com/Metacreation-Lab/MIDI-GPT) transformer model.

- **Fill in missing bars** — select a region and the model generates notes that fit your existing arrangement
- **Generate new tracks** — create empty bars, name the track by instrument, and let the model compose from scratch
- **Steer the output** — control density, polyphony, and note duration per track from the dashboard
- **Iterative refinement** — regenerate any bar, track, or region until you get what you want
- **Context-aware** — the model reads surrounding MIDI and produces results that fit the key, groove, and texture

**Related docs:** [INSTRUMENTS.md](INSTRUMENTS.md) — MIDI instrument reference and track naming keywords · [VST.md](VST.md) — free VST recommendations for synthesizing all GM instruments

---

## Table of Contents

- [MIDI-GPT for REAPER](#midi-gpt-for-reaper)
  - [Table of Contents](#table-of-contents)
  - [How It Works](#how-it-works)
  - [Requirements](#requirements)
  - [Installation](#installation)
    - [Quick Install (Release Package)](#quick-install-release-package)
    - [Install from Source](#install-from-source)
  - [REAPER Setup](#reaper-setup)
  - [Usage Tutorial](#usage-tutorial)
    - [1. Start the Server](#1-start-the-server)
    - [2. Set Up Your Session](#2-set-up-your-session)
    - [3. Select Context and Target Bars](#3-select-context-and-target-bars)
    - [4. Run Generation](#4-run-generation)
    - [Generating into Empty Tracks](#generating-into-empty-tracks)
    - [Tips and Common Gotchas](#tips-and-common-gotchas)
  - [Controls Reference](#controls-reference)
    - [Global Options](#global-options)
    - [Track Controls (Per-Track)](#track-controls-per-track)
      - [Yellow Model Parameters](#yellow-model-parameters)
      - [Prism Model Parameters](#prism-model-parameters)
      - [Expressive Model Parameters](#expressive-model-parameters)
      - [Pitch Mask & Remix](#pitch-mask--remix-all-models-if-the-loaded-checkpoint-supports-them)
  - [Running Tests](#running-tests)
  - [Building a Release Package](#building-a-release-package)

---

## How It Works

MIDI-GPT for REAPER has three components:

1. **Inference Server** (`midigpt-http`) — Starts a stateless FastAPI server listening for generation requests on port `3456` (binds `0.0.0.0` by default, so it can run on a different machine than REAPER, e.g. a GPU workstation on the same network).
2. **REAPER Script** (`REAPER_midigpt_infill.py`) — Reads your REAPER session (MIDI, instruments, control values), sends a generation payload to the server, and writes the result back into your project. Talks to `http://127.0.0.1:3456` by default; run the **MIDI-GPT: Set server address** action to point it at a different IP/domain.
3. **Dashboard** (`REAPER_midigpt_dashboard.py`) — A single ReaImGui window for the whole workflow: server address, SoundFont/track setup, global options, per-track controls (density, polyphony, key signature, pitch mask, remix, etc.), and running generation.

The model sees your existing MIDI as context and generates new notes for the bars you select, producing results that fit musically with the surrounding material.

---

## Requirements

- **REAPER** 64-bit (v6 or later) — [Download REAPER](https://www.reaper.fm/download.php) (make sure to select the **64-bit** version for your OS)
- **ReaImGui** — the REAPER extension the dashboard UI is built with. Install it via **Extensions > ReaPack > Browse packages**, search `ReaImGui`, install, then restart REAPER. (Don't have ReaPack? Get it first: [reapack.com](https://reapack.com/).) The installer checks for this and warns you if it's missing.
- **Python** 3.10 – 3.12 (3.12 recommended) — [Download Python](https://www.python.org/downloads/)
- **Git** (required for installer package check)
- **OS:** macOS, Linux, or Windows

---

## Installation

### One-Line Install (macOS / Linux)

Paste this into a terminal — it installs everything and offers to start the server immediately:

```bash
curl -fsSL https://raw.githubusercontent.com/Metacreation-Lab/midigpt-REAPER/main/bootstrap.sh | bash
```

**Requirements:** Python 3.10, 3.11, or 3.12 and `git`. If Python is missing, the installer will tell you exactly how to get it for your OS (Homebrew on macOS, `apt` on Ubuntu/Debian, or python.org for anything else). After installing, re-run the same command.

**To update later:** `cd ~/midigpt-REAPER && ./update.sh`

**To uninstall:** `cd ~/midigpt-REAPER && ./uninstall.sh`

---

### Quick Install (Release Package)

Download the release zip, extract it, and double-click the installer for your OS:

| OS | Installer | What to double-click |
|----|-----------|---------------------|
| macOS | Included | `Install - Mac.command` |
| Linux | Included | `Install - Linux.sh` |
| Windows | Included | `Install - Windows.bat` |

The installer handles everything automatically:

1. **System dependencies** — Detects `python` and `git`.
2. **Python virtual environment** — Creates `.venv/` with PyTorch.
3. **MIDI-GPT backend** — Installs the sibling `MIDI-GPT` library in editable mode.
4. **REAPER symlinks** — Links the plugin's Scripts into your REAPER config folder, and checks whether the ReaImGui extension (required by the dashboard UI) is already installed, printing instructions if not.
5. **REAPER configuration** — Edits `reaper.ini` to enable ReaScript and set the Python library path (quit REAPER first).
6. **Desktop shortcut** — Places a "Start MIDI-GPT Server" launcher on your Desktop.

> **Note:** REAPER should be closed during installation. REAPER overwrites `reaper.ini` when it quits, so any changes made while it's running will be lost.

### Install from Source

If you cloned this repo and want to link a local `MIDI-GPT` backend repository:

```bash
# macOS / Linux
./install.sh --midigpt-src=/path/to/MIDI-GPT

# Windows (Git Bash / MSYS)
./install-windows.sh --midigpt-src=/c/path/to/MIDI-GPT
```

**Installer flags:**

| Option | Description |
|--------|-------------|
| `--midigpt-src=PATH` | Path to the MIDI-GPT backend source folder |
| `--skip-deps` | Skip system dependency checks |
| `--skip-reaper-config` | Don't modify `reaper.ini` |

---

## REAPER Setup

1. **Install ReaImGui (required, one-time):** **Extensions > ReaPack > Browse packages**, search `ReaImGui`, install, then restart REAPER. The dashboard won't open without it. (Don't have ReaPack? Get it first: [reapack.com](https://reapack.com/).)

2. **Load the ReaScript Actions:**
   * Open the Action List: **Actions > Show Action List** (or press `?`).
   * Click **New action**, then select **Load ReaScript...**.
   * Browse to: `~/Library/Application Support/REAPER/Scripts/MIDI-GPT/` (or `%APPDATA%\REAPER\Scripts\MIDI-GPT\` on Windows).
   * Select **`REAPER_midigpt_dashboard.py`** — this is the primary UI, load it first.
   * Also load `REAPER_midigpt_infill.py`, `REAPER_midigpt_set_server.py`, `REAPER_midigpt_setup_tracks.py`, `REAPER_midigpt_set_soundfont_template.py`, and `REAPER_midigpt_apply_soundfont_template.py` — the dashboard calls into these directly, but loading them separately also gives you keyboard-shortcut access to each one on its own.

3. **Open the dashboard:** run **MIDI-GPT: Dashboard**. It's a single window covering server address, global options, and per-track controls (density, polyphony, duration, key signature, pitch mask, remix, etc.) — see [Controls Reference](#controls-reference) for what each control does. Values are saved per-project, so you only need to set them once per session.

4. **Set up tracks (optional, saves manual work):**
   * The dashboard's **Setup Tracks** button (or the standalone **MIDI-GPT: Setup tracks** action, `REAPER_midigpt_setup_tracks.py`) auto-detects each track's GM instrument from its MIDI content and adds a Sforzando instance to any track that doesn't have one yet.
   * Instrument detection reads each track's actual MIDI content (channel 10 / Program Change events), not the track name, since imported files usually give every track the same name. Tracks it can't resolve that way are prompted for individually — a native dropdown list of all 128 GM instruments on macOS, or a keyword-entry dialog (piano/bass/drums/etc.) elsewhere. Resolved tracks are renamed to the matching name from [INSTRUMENTS.md](INSTRUMENTS.md) (e.g. `acoustic_grand_piano`, `drums`) so they're readable at a glance.
   * **SoundFont setup (one-time):** the first run adds an empty Sforzando to every track. Manually import your `.sf2` (e.g. Arachno, see [VST.md](VST.md)) into *one* track's Sforzando, then run **MIDI-GPT: Use as soundfont template** on that track. From then on, `Setup tracks` clones that already-loaded instance onto any track that doesn't have an instrument yet — no re-importing the SoundFont per track. To replace tracks that already got an empty Sforzando before the template existed, select them and run **MIDI-GPT: Apply soundfont template to selected tracks**.
   * **Auto-selecting the instrument program (one-time per instrument):** by default you still pick the program inside Sforzando manually (the console output tells you which one, e.g. `electric_bass_finger`, per track). To make `Setup tracks` select it for you, save it as a REAPER FX preset once: with that program showing in Sforzando, open the FX window's **Presets** dropdown → **Save preset...**, and name it `MIDI-GPT: ` + the canonical name (e.g. `MIDI-GPT: electric_bass_finger`) — the `MIDI-GPT: ` prefix keeps these separate from any of your own presets so nothing clashes. Once a preset exists for an instrument, every future track resolved to it gets that program selected automatically — this only needs doing once per instrument you actually use, ever.
   * Safe to re-run `Setup tracks`: a track's instrument/preset is only ever touched if this script added the instrument itself, and only until its preset selection is confirmed once — after that (or on any instrument you added/changed by hand), re-running leaves it alone. A preset that didn't take effect on one run (still loading) is retried automatically on the next.

---

## Usage Tutorial

### 1. Start the Server

Double-click the **`Start MIDI-GPT Server`** shortcut on your Desktop, or run from the repo:

```bash
./start_midigpt_server.sh                                          # yellow_medium (default)
./start_midigpt_server.sh --pretrained prism_medium                # Prism model
./start_midigpt_server.sh --pretrained expressive_medium           # Expressive model
./start_midigpt_server.sh --ckpt /path/to/model.safetensors        # Local checkpoint
```

The model is fixed for the lifetime of the server process. To switch models, stop the server and restart it with a different flag. The dashboard auto-detects the running model via the server's `/info` endpoint and adjusts which per-track controls it shows accordingly.

### 2. Set Up Your Session

**Name your tracks** so the plugin can identify instruments. Track names are matched case-insensitively by keyword — a track named `"my piano"` or `"PIANO chords"` both resolve to piano. Unrecognized names default to piano. See [INSTRUMENTS.md](INSTRUMENTS.md) for the full keyword list.

**Add MIDI context** to your tracks. The model uses surrounding notes as musical context when generating. Tracks with more coherent existing content produce more coherent output.

**Open the dashboard** (**MIDI-GPT: Dashboard**) and set per-track controls for any track where you want explicit control over density, polyphony, and duration. This is optional for tracks with existing content, but important for empty tracks — see [Generating into Empty Tracks](#generating-into-empty-tracks).

### 3. Select Context and Target Bars

**Set the loop region (context window):**
- Enable the REAPER loop and position it over the bars you want the model to use as musical context.
- The loop region should match the model's context size (`model_dim`, shown in the dashboard's Global Options panel — 4 bars for Yellow by default).
- Without a loop region, the model uses the entire project as context, which is slower but still works.

**Set the time selection (generation target):**
- Draw a time selection over the bars you want to generate or infill. This is what gets replaced.
- If a MIDI item spans multiple bars and you only want to generate part of it, **split the item first** so only the target bars fall within your time selection.
- You can target a single bar, a horizontal range across one track, or a vertical range across multiple tracks simultaneously.

### 4. Run Generation

Click **Run Infill** in the dashboard, or open the Action List (`?`) and run **`Script: REAPER_midigpt_infill.py`** directly.

The script reads your MIDI items and the dashboard's saved control values, sends a generation request to the server, and writes the result back. Generated MIDI **replaces** whatever was in the target bars. Run it again to regenerate with different settings or a different random seed.

### Generating into Empty Tracks

When generating into bars that contain no existing MIDI, the model has no content to infer controls from. Without explicit per-track settings, it tends toward silence or sparse output.

To get useful results on empty tracks:

1. Create the track, name it with an instrument keyword, and create an empty MIDI item covering the target bars.
2. In the dashboard's Track Controls for that track, set controls appropriate to the instrument. **Density only affects drum tracks; Polyphony and Note Duration only affect melodic tracks** — the dashboard shows only the controls relevant to the track it detects, so which columns apply depends on what kind of track you're setting up:

| Instrument type | Polyphony (min/max) | Duration |
|-----------------|---------------------|----------|
| Monophonic (flute, bass, lead) | 1 / 1 | Short–medium |
| Chordal (piano, pads, guitar) | 3 / 6 | Medium–long |
| Arpeggio | 1 / 2 | Short |

| Drum density | Setting |
|--------------|---------|
| Sparse (kick/snare only) | Low |
| Standard groove | Medium |
| Busy/fills | High |

3. Run generation. Adjust the controls and regenerate until you get the character you want.

### Tips and Common Gotchas

- **Loop size and model_dim**: The loop region should be exactly `model_dim` bars (check the dashboard's Global Options panel). A mismatched loop forces the model to process more context than necessary, which slows generation.
- **Bars per step can exceed model_dim**: You can generate more bars than `model_dim` in one run. The model steps through the target bars sequentially at `model_dim`-sized increments.
- **No per-track controls on empty bars**: Without dashboard settings for a track, controls are inferred from existing content. On empty bars this biases strongly toward silence. Always set per-track controls when generating into empty tracks — polyphony/duration for melodic tracks, density for drum tracks.
- **Density vs. Polyphony/Duration**: Density only ever affects drum tracks; Polyphony, Note Duration, Key Signature, Pitch Range, and Pitch Class Set only ever affect melodic tracks. Setting one on the wrong track type is a silent no-op — the dashboard hides whichever half doesn't apply once it detects the track's instrument.
- **Instrument fallback**: Tracks with names the plugin doesn't recognize default to piano (instrument 0). If a track is generating piano-like output unexpectedly, check the track name against [INSTRUMENTS.md](INSTRUMENTS.md).

---

## Controls Reference

All controls below live in the **MIDI-GPT: Dashboard** window (`REAPER_midigpt_dashboard.py`), saved per-project — you only need to set them once per session, not per generation run.

### Global Options

| Parameter | Slider Range | Description |
|-----------|--------------|-------------|
| **Temperature** | 0.1 to 3.0 | Controls generation randomness. Lower = more conservative. |
| **Context Size** | 2 to 16 | The model's context window size in bars (default: 4). |
| **Bars Per Step** | 1 to Context Size | Number of bars generated per inference step. |
| **Tracks Per Step** | 1 to 16 | Number of tracks processed per step. |
| **Polyphony Hard Limit** | 0 to 32 | Global limit on simultaneous note onsets (0 = disabled). |
| **Density Hard Limit** | 0 to 64 | Global limit on note onsets per bar (0 = disabled). |
| **Max Attempts** | 1 to 10 | Max tries per step if checks fail. |
| **Temp Escalation** | 1.0 to 3.0 | Rand multiplier per failed attempt. |
| **Top-p** | 0.0 to 1.0 | Nucleus sampling probability threshold (1.0 = off). |
| **Top-k** | 0 to 500 | Keeps top-k highest-prob tokens (0 = off). |
| **Anti-nucleus mask_p** | 0.0 to 0.95 | Chops most-likely tokens to force novelty (0.0 = off). |
| **Anti-nucleus mask_k** | 0 to 100 | Chops top-k tokens after top_* filtering (0 = off). |
| **Random Seed** | -1 to 999999 | Fixed seed for reproducibility (-1 = random). |
| **Batch Candidates** | 1 to 16 | Generate multiple candidates per run and pick the best one in the dashboard. Disables token streaming above 1. |
| **Checks** | None, Novelty, Silence, Both | Enables validation filters. |
| **Shuffle Steps** | No, Yes | Shuffles order of generation steps. |

### Track Controls (Per-Track)

Density only ever affects **drum** tracks. Polyphony, Note Duration, Key Signature, Pitch Range, and Pitch Class Set only ever affect **melodic** tracks — setting one on the wrong track type is a silent no-op server-side. The dashboard detects each track's instrument and shows only the half that applies; if it can't tell, it shows both and says so.

#### Yellow Model Parameters
* **Density** (0-10, drums only): Note density level.
* **Min / Max Polyphony** (0-10, melodic only): Simultaneous note bounds.
* **Min / Max Note Duration** (0-6, melodic only): Note duration bounds, quantized.
* **Autoregressive**: Freely generate full track bar-by-bar.
* **Ignore**: Ignores this track for generation (treats as context).

#### Prism Model Parameters
* **Key Signature** (0-25, melodic only): Constrain output to a key (0 = any).
* **Pitch Range** (0-128, melodic only): Max pitch span in semitones (0 = any).
* **Silence Proportion** (0-10, both track types): Target proportion of silence (0 = any).
* **Min / Max Note Duration** (0-6, melodic only): Quantized note duration bounds.
* **Density** (0-10, drums only): Per-bar note density (applied to each generated bar).
* **Min / Max Polyphony** (0-10, melodic only): Per-bar simultaneous note bounds.
* **Pitch Class Set** (0-13, melodic only): Number of distinct pitch classes per bar (0 = any).
* **Autoregressive**: Freely generate full track bar-by-bar.
* **Ignore**: Ignores this track for generation (treats as context).

#### Expressive Model Parameters
* All Prism parameters, plus **NOMML** (0-13, both track types): Quantization grid depth controlling microtiming expressivity (0 = any, 13 = fully expressive).

#### Pitch Mask & Remix (all models, if the loaded checkpoint supports them)
* **Pitch Mask**: Off, constrain to a musical scale (root + preset), or an explicit set of allowed pitch classes — optionally reweighted toward a register (uniform range or a normal distribution around a mean pitch).
* **Remix**: Regenerates a track's existing bars as a variation of what's already there (amount 0-1, pitch-only or pitch+duration) instead of generating fresh content.

---

## Running Tests

To run the full suite of unit and integration tests:

```bash
./tests/integration/test_install.sh
```

---

## Building a Release Package

To package the plugin, scripts, installers, and documentation for release:

```bash
./build_release.sh
```
This generates a ZIP file named `MIDI-GPT-for-REAPER-[DATE].zip` in the repository root.
