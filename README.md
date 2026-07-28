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
- **Steer the output** — control density, polyphony, and note duration per track with JSFX sliders
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
    - [Global Options (Monitor FX or Master Track)](#global-options-monitor-fx-or-master-track)
    - [Track Options (Per-Track FX)](#track-options-per-track-fx)
      - [Yellow Model Parameters](#yellow-model-parameters)
      - [Prism Model Parameters](#prism-model-parameters)
      - [Expressive Model Parameters](#expressive-model-parameters)
  - [Running Tests](#running-tests)
  - [Building a Release Package](#building-a-release-package)

---

## How It Works

MIDI-GPT for REAPER has three components:

1. **Inference Server** (`midigpt-http`) — Starts a stateless FastAPI server listening for generation requests on `127.0.0.1:3456`.
2. **REAPER Script** (`REAPER_midigpt_infill.py`) — Reads your REAPER session (MIDI, instruments, control values), sends a generation payload to the server, and writes the result back into your project.
3. **JSFX Controls** — Lightweight REAPER effects that give you sliders for temperature, density, polyphony, key signature, pitch range, and other generation parameters.

The model sees your existing MIDI as context and generates new notes for the bars you select, producing results that fit musically with the surrounding material.

---

## Requirements

- **REAPER** 64-bit (v6 or later) — [Download REAPER](https://www.reaper.fm/download.php) (make sure to select the **64-bit** version for your OS)
- **Python** 3.10 – 3.12 (3.12 recommended) — [Download Python](https://www.python.org/downloads/)
- **Git** (required for installer package check)
- **OS:** macOS, Linux, or Windows

---

## Installation

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
4. **REAPER symlinks** — Links Scripts and Effects into your REAPER config folder.
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

1. **Load the ReaScript Action:**
   * Open the Action List: **Actions > Show Action List** (or press `?`).
   * Click **New action**, then select **Load ReaScript...**.
   * Browse to: `~/Library/Application Support/REAPER/Scripts/MIDI-GPT/` (or `%APPDATA%\REAPER\Scripts\MIDI-GPT\` on Windows).
   * Select **`REAPER_midigpt_infill.py`** and click Open.

2. **Add Global Options JSFX (required):**
   * Open the Monitoring Effects window (**View > Monitoring Effects**).
   * Click **Add** and search for **`JS: MIDI-GPT Global Options`**.
   * Add it to the Monitoring FX chain. This must be present for any generation to work.

3. **Add Track Options JSFX (optional, per track):**
   * On tracks where you want per-track control over density, polyphony, and duration, add the track JSFX.
   * Search for **`JS: MIDI-GPT Track Options (Yellow)`**, **`(Prism)`**, or **`(Expressive)`** (matching the model loaded on the server) and add it to the track's FX chain.
   * Tracks without this JSFX use default values inferred from existing content — see [Tips and Common Gotchas](#tips-and-common-gotchas) for when this matters.

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

The model is fixed for the lifetime of the server process. To switch models, stop the server and restart it with a different flag. The REAPER script auto-detects the running model via the server's `/info` endpoint and loads the correct Track Options JSFX automatically.

### 2. Set Up Your Session

**Name your tracks** so the plugin can identify instruments. Track names are matched case-insensitively by keyword — a track named `"my piano"` or `"PIANO chords"` both resolve to piano. Unrecognized names default to piano. See [INSTRUMENTS.md](INSTRUMENTS.md) for the full keyword list.

**Add MIDI context** to your tracks. The model uses surrounding notes as musical context when generating. Tracks with more coherent existing content produce more coherent output.

**Add Track Options JSFX** to any track where you want explicit control over density, polyphony, and duration. This is optional for tracks with existing content, but important for empty tracks — see [Generating into Empty Tracks](#generating-into-empty-tracks).

### 3. Select Context and Target Bars

**Set the loop region (context window):**
- Enable the REAPER loop and position it over the bars you want the model to use as musical context.
- The loop region should match the model's context size (`model_dim`, shown in the Global Options JSFX — 4 bars for Yellow by default).
- Without a loop region, the model uses the entire project as context, which is slower but still works.

**Set the time selection (generation target):**
- Draw a time selection over the bars you want to generate or infill. This is what gets replaced.
- If a MIDI item spans multiple bars and you only want to generate part of it, **split the item first** so only the target bars fall within your time selection.
- You can target a single bar, a horizontal range across one track, or a vertical range across multiple tracks simultaneously.

### 4. Run Generation

Open the Action List (`?`) and run **`Script: REAPER_midigpt_infill.py`**.

The script reads your MIDI items and JSFX slider values, sends a generation request to the server, and writes the result back. Generated MIDI **replaces** whatever was in the target bars. You can run the script again to regenerate with different settings or a different random seed.

### Generating into Empty Tracks

When generating into bars that contain no existing MIDI, the model has no content to infer controls from. Without explicit Track Options JSFX settings, it tends toward silence or sparse output.

To get useful results on empty tracks:

1. Create the track, name it with an instrument keyword, and create an empty MIDI item covering the target bars.
2. Add **Track Options JSFX** to the track and set controls appropriate to the instrument:

| Instrument type | Polyphony (min/max) | Duration | Density |
|-----------------|---------------------|----------|---------|
| Monophonic (flute, bass, lead) | 1 / 1 | Short–medium | Low |
| Chordal (piano, pads, guitar) | 3 / 6 | Medium–long | Medium |
| Arpeggio | 1 / 2 | Short | Medium–high |
| Drums | 1 / 4 | Short | High |

3. Run generation. Adjust sliders and regenerate until you get the character you want.

### Tips and Common Gotchas

- **Loop size and model_dim**: The loop region should be exactly `model_dim` bars (check the Global Options JSFX). A mismatched loop forces the model to process more context than necessary, which slows generation.
- **Bars per step can exceed model_dim**: You can generate more bars than `model_dim` in one run. The model steps through the target bars sequentially at `model_dim`-sized increments.
- **No Track FX on empty bars**: Without Track FX, controls are inferred from existing content. On empty bars this biases strongly toward silence. Always add Track FX when generating into empty tracks and set polyphony, duration, and density explicitly.
- **Instrument fallback**: Tracks with names the plugin doesn't recognize default to piano (instrument 0). If a track is generating piano-like output unexpectedly, check the track name against [INSTRUMENTS.md](INSTRUMENTS.md).

---

## Controls Reference

### Global Options (Monitor FX or Master Track)

| Parameter | Slider Range | Description |
|-----------|--------------|-------------|
| **Temperature** | 0.1 to 3.0 | Controls generation randomness. Lower = more conservative. |
| **Context Size** | 2 to 16 | The model's context window size in bars (default: 4). |
| **Bars Per Step** | 1 to 16 | Number of bars generated per inference step. |
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
| **Checks** | None, Novelty, Silence, Both | Enables validation filters. |
| **Shuffle Steps** | No, Yes | Shuffles order of generation steps. |

### Track Options (Per-Track FX)

#### Yellow Model Parameters
* **Density** (0-10): Note density level.
* **Min Polyphony** (0-10): Min simultaneous notes.
* **Max Polyphony** (0-10): Max simultaneous notes.
* **Min Note Duration** (0-6): Min note duration quantized.
* **Max Note Duration** (0-6): Max note duration quantized.
* **Autoregressive**: Freely generate full track bar-by-bar.
* **Ignore**: Ignores this track for generation (treats as context).

#### Prism Model Parameters
* **Key Signature** (0-25): Constrain output to a key (0 = any).
* **Pitch Range** (0-128): Max pitch span in semitones (0 = any).
* **Silence Proportion** (0-10): Target proportion of silence (0 = any).
* **Min / Max Note Duration** (0-6): Quantized note duration bounds.
* **Density** (0-10): Per-bar note density (applied to each generated bar).
* **Min / Max Polyphony** (0-10): Per-bar simultaneous note bounds.
* **Pitch Class Set** (0-13): Number of distinct pitch classes per bar (0 = any).
* **Autoregressive**: Freely generate full track bar-by-bar.
* **Ignore**: Ignores this track for generation (treats as context).

#### Expressive Model Parameters
* All Prism parameters, plus **NOMML** (0-13): Quantization grid depth controlling microtiming expressivity (0 = any, 13 = fully expressive).

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
