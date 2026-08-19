# Instrument Names

MIDI-GPT uses General MIDI instrument names to identify tracks. **The track name is ground truth** — `REAPER_midigpt_infill.py` matches your track's name against the keyword list below (case-insensitive, substring match) to resolve it to one of the canonical instrument names shown in the table.

A track's MIDI content (channel 10 for drums, or an embedded Program Change event) is only used as a *fallback*, for a track whose name doesn't match any keyword — and it's what the dashboard's **Setup Tracks** action uses to auto-assign a name in the first place. Once a track has a resolved name, that name is what determines its instrument for generation, not whatever MIDI content happens to be on it. A track with no name match and no detectable MIDI content defaults to piano.

**To set a track's instrument:** rename it with a recognizable keyword (e.g. `"my piano"`, `"PIANO chords"`, `"bass"` all resolve correctly — matching is case-insensitive and just needs the keyword somewhere in the name), or run **MIDI-GPT: Setup tracks** to have it auto-detected and renamed for you from existing MIDI content.

The mapping below shows **MIDI Program Number** -> **Internal Name** — this is the canonical name space your track names get resolved into, and what a soundfont program in Sforzando needs to match for [VST.md](VST.md)'s auto-preset-selection to work.

## Drums

A track named `drums` (or containing the word `drum`) resolves to drums. If unresolved by name, a track whose MIDI content is on channel 10 (or already has instrument number 128 in REAPER's track info) also resolves to drums.

| Program | Internal Name |
|---------|--------------|
| (any) | `drums` |

## Piano (0-7)

| Program | Internal Name |
|---------|--------------|
| 0 | `acoustic_grand_piano` |
| 1 | `bright_acoustic_piano` |
| 2 | `electric_grand_piano` |
| 3 | `honky_tonk_piano` |
| 4 | `electric_piano_1` |
| 5 | `electric_piano_2` |
| 6 | `harpsichord` |
| 7 | `clavi` |

## Chromatic Percussion (8-15)

| Program | Internal Name |
|---------|--------------|
| 8 | `celesta` |
| 9 | `glockenspiel` |
| 10 | `music_box` |
| 11 | `vibraphone` |
| 12 | `marimba` |
| 13 | `xylophone` |
| 14 | `tubular_bells` |
| 15 | `dulcimer` |

## Organ (16-23)

| Program | Internal Name |
|---------|--------------|
| 16 | `drawbar_organ` |
| 17 | `percussive_organ` |
| 18 | `rock_organ` |
| 19 | `church_organ` |
| 20 | `reed_organ` |
| 21 | `accordion` |
| 22 | `harmonica` |
| 23 | `tango_accordion` |

## Guitar (24-31)

| Program | Internal Name |
|---------|--------------|
| 24 | `acoustic_guitar_nylon` |
| 25 | `acoustic_guitar_steel` |
| 26 | `electric_guitar_jazz` |
| 27 | `electric_guitar_clean` |
| 28 | `electric_guitar_muted` |
| 29 | `overdriven_guitar` |
| 30 | `distortion_guitar` |
| 31 | `guitar_harmonics` |

## Bass (32-39)

| Program | Internal Name |
|---------|--------------|
| 32 | `acoustic_bass` |
| 33 | `electric_bass_finger` |
| 34 | `electric_bass_pick` |
| 35 | `fretless_bass` |
| 36 | `slap_bass_1` |
| 37 | `slap_bass_2` |
| 38 | `synth_bass_1` |
| 39 | `synth_bass_2` |

## Strings (40-47)

| Program | Internal Name |
|---------|--------------|
| 40 | `violin` |
| 41 | `viola` |
| 42 | `cello` |
| 43 | `contrabass` |
| 44 | `tremolo_strings` |
| 45 | `pizzicato_strings` |
| 46 | `orchestral_harp` |
| 47 | `timpani` |

## Ensemble (48-55)

| Program | Internal Name |
|---------|--------------|
| 48 | `string_ensemble_1` |
| 49 | `string_ensemble_2` |
| 50 | `synth_strings_1` |
| 51 | `synth_strings_2` |
| 52 | `choir_aahs` |
| 53 | `voice_oohs` |
| 54 | `synth_voice` |
| 55 | `orchestra_hit` |

## Brass (56-63)

| Program | Internal Name |
|---------|--------------|
| 56 | `trumpet` |
| 57 | `trombone` |
| 58 | `tuba` |
| 59 | `muted_trumpet` |
| 60 | `french_horn` |
| 61 | `brass_section` |
| 62 | `synth_brass_1` |
| 63 | `synth_brass_2` |

## Reed (64-71)

| Program | Internal Name |
|---------|--------------|
| 64 | `soprano_sax` |
| 65 | `alto_sax` |
| 66 | `tenor_sax` |
| 67 | `baritone_sax` |
| 68 | `oboe` |
| 69 | `english_horn` |
| 70 | `bassoon` |
| 71 | `clarinet` |

## Pipe (72-79)

| Program | Internal Name |
|---------|--------------|
| 72 | `piccolo` |
| 73 | `flute` |
| 74 | `recorder` |
| 75 | `pan_flute` |
| 76 | `blown_bottle` |
| 77 | `shakuhachi` |
| 78 | `whistle` |
| 79 | `ocarina` |

## Synth Lead (80-87)

| Program | Internal Name |
|---------|--------------|
| 80 | `lead_1_square` |
| 81 | `lead_2_sawtooth` |
| 82 | `lead_3_calliope` |
| 83 | `lead_4_chiff` |
| 84 | `lead_5_charang` |
| 85 | `lead_6_voice` |
| 86 | `lead_7_fifths` |
| 87 | `lead_8_bass__lead` |

## Synth Pad (88-95)

| Program | Internal Name |
|---------|--------------|
| 88 | `pad_1_new_age` |
| 89 | `pad_2_warm` |
| 90 | `pad_3_polysynth` |
| 91 | `pad_4_choir` |
| 92 | `pad_5_bowed` |
| 93 | `pad_6_metallic` |
| 94 | `pad_7_halo` |
| 95 | `pad_8_sweep` |

## Synth Effects (96-103)

| Program | Internal Name |
|---------|--------------|
| 96 | `fx_1_rain` |
| 97 | `fx_2_soundtrack` |
| 98 | `fx_3_crystal` |
| 99 | `fx_4_atmosphere` |
| 100 | `fx_5_brightness` |
| 101 | `fx_6_goblins` |
| 102 | `fx_7_echoes` |
| 103 | `fx_8_sci_fi` |

## Ethnic (104-111)

| Program | Internal Name |
|---------|--------------|
| 104 | `sitar` |
| 105 | `banjo` |
| 106 | `shamisen` |
| 107 | `koto` |
| 108 | `kalimba` |
| 109 | `bag_pipe` |
| 110 | `fiddle` |
| 111 | `shanai` |

## Percussive (112-119)

| Program | Internal Name |
|---------|--------------|
| 112 | `tinkle_bell` |
| 113 | `agogo` |
| 114 | `steel_drums` |
| 115 | `woodblock` |
| 116 | `taiko_drum` |
| 117 | `melodic_tom` |
| 118 | `synth_drum` |
| 119 | `reverse_cymbal` |

## Sound Effects (120-127)

| Program | Internal Name |
|---------|--------------|
| 120 | `guitar_fret_noise` |
| 121 | `breath_noise` |
| 122 | `seashore` |
| 123 | `bird_tweet` |
| 124 | `telephone_ring` |
| 125 | `helicopter` |
| 126 | `applause` |
| 127 | `gunshot` |

## Tips

- The model was trained on General MIDI data, so it performs best with standard GM instruments.
- **Piano, guitar, bass, strings, and drums** are the most commonly represented in the training data and tend to produce the best results.
- If you're using a synth or non-GM instrument, pick the closest GM instrument name for best generation quality.
- **Name your tracks** — the track name is what determines the instrument, not any MIDI content on it. A generic name like `"Track 1"` with no keyword match falls back to MIDI-content detection and finally defaults to piano, so an unresolved name can silently generate the wrong instrument's content. Run **MIDI-GPT: Setup tracks** to auto-detect and rename tracks from their MIDI content instead of doing it by hand.
