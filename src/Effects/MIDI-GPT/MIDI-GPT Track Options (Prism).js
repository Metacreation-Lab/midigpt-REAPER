desc:MIDI-GPT Track Options (Prism)

slider1:jsfx_id=349583027<349583027,349583027,1>-jsfx_id

slider2:key_signature=0<0,25,1{Any,C Maj,C# Maj,D Maj,D# Maj,E Maj,F Maj,F# Maj,G Maj,G# Maj,A Maj,A# Maj,B Maj,C Min,C# Min,D Min,D# Min,E Min,F Min,F# Min,G Min,G# Min,A Min,A# Min,B Min,No Key}>Key Signature
slider3:pitch_range=0<0,128,1>Pitch Range (0: Any)
slider4:silence_proportion=0<0,10,1>Silence Proportion (0: Any)
slider5:min_note_duration_q=0<0,6,1{Any,32nd,16th,8th,Quarter,Half,Whole}>Note Duration Min
slider6:max_note_duration_q=0<0,6,1{Any,32nd,16th,8th,Quarter,Half,Whole}>Note Duration Max
slider7:density=0<0,10,1>Density (0: Any)
slider8:min_polyphony_q=0<0,10,1>Polyphony Min (0: Any)
slider9:max_polyphony_q=0<0,10,1>Polyphony Max (0: Any)
slider10:pitch_class_set=0<0,13,1>Pitch Class Set Size (0: Any)

// Behavior flags
slider11:autoregressive=0<0,1,1{Off,On}>Autoregressive
slider12:ignore=0<0,1,1{Off,On}>Ignore Track

in_pin:none
out_pin:none

@init

@slider
min_polyphony_q > max_polyphony_q && max_polyphony_q > 0 ? min_polyphony_q = max_polyphony_q;
min_note_duration_q > max_note_duration_q && max_note_duration_q > 0 ? min_note_duration_q = max_note_duration_q;
