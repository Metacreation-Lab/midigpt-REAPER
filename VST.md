# README — Recommended Instrument Setup (REAPER)

---

## Required Components

### 1. Sforzando (SFZ Player)

Download:
[https://www.plogue.com/francais/telechargements.html#sforzando](https://www.plogue.com/francais/telechargements.html#sforzando)

* Free SFZ sampler plugin (VST/AU)
* Used to load and play the General MIDI soundfont

---

### 2. Arachno SoundFont (GM Bank)

Download:
[https://www.arachnosoft.com/main/download.php?id=soundfont-sf2](https://www.arachnosoft.com/main/download.php?id=soundfont-sf2)

* Complete **General MIDI soundfont**
* Covers all **128 GM instruments (programs 0–127)** + drum kits
* Provides the mapping required by this project

---

### 3. MT Power Drum Kit 2 (Drums)

Download:
[https://www.powerdrumkit.com/download76187.php](https://www.powerdrumkit.com/download76187.php)

* High-quality acoustic drum plugin (VST/AU)
* Used instead of GM drums for better realism

---

## Installation

### Step 1 — Install Plugins

1. Install **Sforzando**
2. Install **MT Power Drum Kit 2**
3. Place the **Arachno `.sf2` file** in a known location (e.g., `Documents/SoundFonts/`)

---

### Step 2 — Rescan Plugins in REAPER

After installation:

1. Open REAPER
2. Go to:
   `Options → Preferences → Plug-ins → VST`
3. Click:

   * **“Re-scan”** 

This ensures REAPER detects newly installed VST instruments.

---

## Usage

### Using VST Instruments in REAPER

1. Create a new track
2. Click the **FX** button on the track
3. Search for the plugin (e.g., *Sforzando*, *MT Power Drum Kit*)
4. Double-click to load it

* Go to `Options → Preferences → Plug-ins → VST`
* Click **Re-scan** or **Clear cache / re-scan**

### Load General MIDI Instruments (Sforzando + Arachno)

1. Create a new track
2. Add **Sforzando** as an FX instrument
3. Inside Sforzando:

    * Click on `Instrument → import` then select the **Arachno `.sf2` file**
    * Select an instrument by clicking on `Instrument → converted → sf2 → ...`

* Each program number corresponds to a GM instrument
* This mapping is required for correct playback of generated MIDI

---

### Load Drums (MT Power Drum Kit)

1. Create a separate track
2. Add **MT Power Drum Kit 2**
3. Route drum MIDI (typically channel 10) to this track

---

## Recommended Track Layout

* Track 1: **Sforzando (GM instruments)**
* Track 2: **MT Power Drum Kit (drums)**

---