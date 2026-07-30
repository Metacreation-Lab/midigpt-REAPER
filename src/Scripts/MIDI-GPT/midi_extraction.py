"""
REAPER MIDI Extractor for MMM
Clean extraction of MIDI content and measure masks from REAPER projects
"""

from typing import List, Tuple, Optional, Dict
from reaper_python import *

# Import existing helper modules if available
try:
    #import mytrackviewstuff as mt
    #import mymidistuff as mm
    HAS_HELPERS = True
except ImportError:
    HAS_HELPERS = False


# --- Instrument Mapping Configuration ---
# Maps track name patterns to MIDI instrument numbers (GM standard)
INST_TO_MATCHING_STRINGS = {
    0: ['piano', 'key'],  # ac grand piano
    1: ['bright'],  # bright ac piano
    2: [],  # electric grand piano
    3: ['honk'],  # honky-tonk piano
    4: ['ep1'],  # electric piano 1
    5: ['ep2'],  # electric piano 2
    6: ['harpsi'],  # harpsichord
    7: ['clav'],  # clavi
    8: ['celest'],  # celesta
    9: ['glock'],  # glock
    10: ['box'],  # music box
    11: ['vibra'],  # vibraphone
    12: ['marimba'],  # marimba
    13: ['xyl'],  # xylophone
    14: ['bell', 'tubu'],  # tubular bells
    15: ['dulcimer'],  # dulcimer
    16: ['organ', 'dorg'],  # drawbar organ
    17: ['porg'],  # percussive organ
    18: ['rorg'],  # rock organ
    19: ['corg'],  # church organ
    20: ['reorg', 'reed'],  # reed organ
    21: ['acc'],  # accordian
    22: ['harmonica'],  # harmonica
    23: ['tango'],  # tango accordian
    24: ['nyl'],  # ac guitar (nylon)
    25: ['steel g', 'sgtr', 'agtr'],  # ac guitar (steel)
    26: ['jazz', 'jgtr'],  # elec guitar (jazz)
    27: ['cgtr'],  # elec guitar (clean)
    28: ['mute', 'mgtr'],  # elec guitar (muted)
    29: ['ogtr', 'over'],  # overdriven guitar
    30: ['gtr', 'guit', 'dist'],  # distortion guitar
    31: ['harmon'],  # guitar harmonics
    32: ['aco'],  # ac bass
    33: ['finger'],  # electric bass (finger)
    34: ['bass'],  # electric bass (pick)
    35: ['fretless'],  # fretless bass
    36: [],  # slap bass 1
    37: ['slap'],  # slap bass 2
    38: ['sbass1'],  # synth bass 1
    39: ['sbass2'],  # synth bass 2
    40: ['violin', 'vn1', 'vn2'],  # violin
    41: ['viola', 'vn3'],  # viola
    42: ['cell', 'vn4'],  # cello
    43: ['contra', 'vn5'],  # contrabass
    44: ['trem'],  # tremolo strings
    45: ['pizz'],  # pizz strings
    46: ['harp'],  # orchestral harp
    47: ['timp'],  # timpani
    48: ['str'],  # string ensemble 1
    49: [],  # string ensemble 2
    50: [],  # synth strings 1
    51: [],  # synth strings 2
    52: ['choir', 'aah'],  # choir aahs
    53: ['ooh'],  # voice oohs
    54: ['voice'],  # synth voice
    55: ['hit', 'orch'],  # orchestra hit
    56: ['trumpet', 'tp'],  # trumpet
    57: ['trom'],  # trombone
    58: ['tuba'],  # tuba
    59: ['muted'],  # muted trumpet
    60: ['french', 'horn', 'fh'],  # french horn
    61: ['brass'],  # brass section
    62: [],  # synth brass 1
    63: [],  # synth brass 2
    64: ['sax'],  # soprano sax
    65: [],  # alto sax
    66: [],  # tenor sax
    67: [],  # baritone sax
    68: ['oboe'],  # oboe
    69: ['english horn', 'english'],  # english horn
    70: ['bsn', 'baso'],  # bassoon
    71: ['clarinet'],  # clarinet
    72: ['picc'],  # piccolo
    73: ['flute', 'fl1', 'fl2'],  # flute
    74: ['recorder'],  # recorder
    75: ['pan'],  # pan flute
    76: ['bottle'],  # blown bottle
    77: ['shak'],  # shakuhachi
    78: ['whistle'],  # whistle
    79: ['ocarina'],  # ocarina
    80: ['square', 'lead1', 'ld1'],  # lead 1 (square)
    81: ['saw', 'lead2', 'ld2'],  # lead 2 (sawtooth)
    82: ['calli', 'lead3', 'ld3'],  # lead 3 (calliope)
    83: ['chiff', 'lead4', 'ld4'],  # lead 4 (chiff)
    84: ['chara', 'lead5', 'ld5'],  # lead 5 (charang)
    85: ['lead 6', 'ld6'],  # lead 6 (voice)
    86: ['fifth', 'lead7', 'ld7'],  # lead 7 (fifths)
    87: ['lead8', 'ld8'],  # lead 8 (bass + lead)
    88: ['pad1', 'new', 'age'],  # pad 1 (new age)
    89: ['pad2', 'warm'],  # pad 2 (warm)
    90: ['pad3', 'polys'],  # pad 3 (polysynth)
    91: ['pad4', 'cpad'],  # pad 4 (choir)
    92: ['pad5', 'bowed'],  # pad 5 (bowed)
    93: ['pad6', 'metallic'],  # pad 6 (metallic)
    94: ['pad7', 'halo'],  # pad 7 (halo)
    95: ['pad8', 'sweep'],  # pad 8 (sweep)
    96: ['fx1', 'rain'],  # FX 1 (rain)
    97: ['fx2', 'soundtrack'],  # FX 2 (soundtrack)
    98: ['fx3', 'crystal'],  # FX 3 (crystal)
    99: ['fx4', 'atmos'],  # FX 4 (atmosphere)
    100: ['fx5'],  # FX 5 (brightness)
    101: ['fx6', 'goblin'],  # FX 6 (goblins)
    102: ['fx7', 'echoes'],  # FX 7 (echoes)
    103: ['fx8', 'sci'],  # FX 8 (sci-fi)
    104: ['sitar'],  # sitar
    105: ['banjo'],  # banjo
    106: ['sham'],  # shamisen
    107: ['koto'],  # koto
    108: ['kali'],  # kalimba
    109: ['bag', 'pipe'],  # bag pipe
    110: ['fiddle'],  # fiddle
    111: ['shan'],  # shanai
    112: ['tink'],  # tinkle bell
    113: ['agog'],  # agogo
    114: ['steel'],  # steel drums
    115: ['wood'],  # woodblock
    116: ['taiko'],  # taiko
    117: ['mtom', 'melodic tom'],  # melodic tom
    118: ['synth drum', 'sdrum'],  # synth drum
    119: ['rev'],  # reverse cymbal
    120: ['fret'],  # guitar fret noise
    121: ['breath'],  # breath noise
    122: ['seashore'],  # seashore
    123: ['bird', 'tweet'],  # bird tweet
    124: ['phone'],  # telephone ring
    125: ['heli'],  # helicopter
    126: ['applause'],  # applause
    127: ['gunshot'],  # gunshot
    128: ['drum', 'kick', 'kik', 'sn', 'tom', 'hat', 'ride', 'crash', 'china', 'tambo']
    # GM drums on channel "10" (channel 9 in 0-based indexing)
}


def get_instrument_from_track_name(track_name: str) -> int:
    """
    Determine instrument number from track name
    Returns the first matching instrument, or 0 (piano) as default
    """
    track_name_lower = track_name.lower()
    
    for inst_num, patterns in INST_TO_MATCHING_STRINGS.items():
        for pattern in patterns:
            if pattern in track_name_lower:
                return inst_num
    
    return 0  # Default to piano


class TimeSelection:
    """Represents a time selection in REAPER"""
    
    def __init__(self, start_time: float, end_time: float, start_measure: int, end_measure: int):
        self.start_time = start_time
        self.end_time = end_time
        self.start_measure = start_measure
        self.end_measure = end_measure
    
    @property
    def has_selection(self) -> bool:
        return self.start_time != self.end_time
    
    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


class MIDINote:
    """Represents a single MIDI note"""
    
    def __init__(self, pitch: int, velocity: int, start_time: float, end_time: float):
        self.pitch = pitch
        self.velocity = velocity
        self.start_time = start_time
        self.end_time = end_time
    
    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


class MIDIMeasure:
    """MIDI content within a single measure"""
    
    def __init__(self, measure_number: int, track_index: int, instrument: int,
                 notes: List[MIDINote], start_time: float, end_time: float,
                 tempo: float = 120.0, time_signature: Tuple[int, int] = (4, 4)):
        self.measure_number = measure_number
        self.track_index = track_index
        self.instrument = instrument  # MIDI instrument number (GM standard)
        self.notes = notes
        self.start_time = start_time
        self.end_time = end_time
        self.tempo = tempo  # BPM at start of measure
        self.time_signature = time_signature  # (numerator, denominator)
    
    @property
    def is_empty(self) -> bool:
        return len(self.notes) == 0
    
    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


class TrackInfo:
    """Information about a REAPER track"""
    
    def __init__(self, track_index: int, track, track_name: str, instrument: int):
        self.track_index = track_index
        self.track = track  # REAPER track object
        self.track_name = track_name
        self.instrument = instrument  # MIDI instrument number
    
    def __repr__(self):
        return f"TrackInfo(idx={self.track_index}, name='{self.track_name}', inst={self.instrument})"


class MIDISongByMeasure:
    """
    Container for MIDI data organized by measures and tracks
    This matches the structure expected by the MMM server
    """
    
    def __init__(self, num_tracks: int, num_measures: int):
        self.num_tracks = num_tracks
        self.num_measures = num_measures
        # measures[track_idx][measure_idx] = MIDIMeasure
        self.measures: List[List[MIDIMeasure]] = [
            [None] * num_measures for _ in range(num_tracks)
        ]
        # Track information (name, instrument, etc.)
        self.track_info: List[TrackInfo] = []
    
    def set_track_info(self, track_info_list: List[TrackInfo]):
        """Set the track information list"""
        self.track_info = track_info_list
    
    def get_track_info(self, track_idx: int) -> Optional[TrackInfo]:
        """Get track info for a specific track index"""
        if 0 <= track_idx < len(self.track_info):
            return self.track_info[track_idx]
        return None
    
    def set_measure(self, track_idx: int, measure_idx: int, measure: MIDIMeasure):
        """Set a measure at the specified track and measure index"""
        if 0 <= track_idx < self.num_tracks and 0 <= measure_idx < self.num_measures:
            self.measures[track_idx][measure_idx] = measure
    
    def get_measure(self, track_idx: int, measure_idx: int) -> Optional[MIDIMeasure]:
        """Get a measure at the specified track and measure index"""
        if 0 <= track_idx < self.num_tracks and 0 <= measure_idx < self.num_measures:
            return self.measures[track_idx][measure_idx]
        return None
    
    def to_dict(self) -> dict:
        """Convert to dictionary format for MMM server"""
        return {
            'num_tracks': self.num_tracks,
            'num_measures': self.num_measures,
            'track_info': [
                {
                    'track_index': ti.track_index,
                    'track_name': ti.track_name,
                    'instrument': ti.instrument
                }
                for ti in self.track_info
            ],
            'measures': [
                [
                    self._measure_to_dict(measure) if measure else None
                    for measure in track_measures
                ]
                for track_measures in self.measures
            ]
        }
    
    @staticmethod
    def _measure_to_dict(measure: MIDIMeasure) -> dict:
        """Convert a single measure to dictionary"""
        return {
            'measure_number': measure.measure_number,
            'track_index': measure.track_index,
            'instrument': measure.instrument,
            'start_time': measure.start_time,
            'end_time': measure.end_time,
            'tempo': measure.tempo,
            'time_signature': measure.time_signature,
            'notes': [
                {
                    'pitch': note.pitch,
                    'velocity': note.velocity,
                    'start_time': note.start_time,
                    'end_time': note.end_time
                }
                for note in measure.notes
            ]
        }


class MeasureMask:
    """
    Tracks which measures should be masked (infilled) by MMM
    """
    
    def __init__(self):
        # Set of (track_idx, measure_idx) tuples
        self.masked_positions: set[Tuple[int, int]] = set()
    
    def add_mask(self, track_idx: int, measure_idx: int):
        """Add a position to mask"""
        self.masked_positions.add((track_idx, measure_idx))
    
    def is_masked(self, track_idx: int, measure_idx: int) -> bool:
        """Check if a position is masked"""
        return (track_idx, measure_idx) in self.masked_positions
    
    def to_list(self) -> List[Tuple[int, int]]:
        """Convert to list format for MMM server"""
        return sorted(list(self.masked_positions))
    
    @property
    def count(self) -> int:
        """Number of masked positions"""
        return len(self.masked_positions)


class TempoMap:
    """Handles tempo and time signature information"""
    
    def __init__(self):
        self.tempo_markers: List[Tuple[float, float]] = []  # (time, bpm)
        self.time_sig_markers: List[Tuple[float, int, int]] = []  # (time, numerator, denominator)
        self.default_tempo = 120.0
        self.default_time_sig = (4, 4)
    
    def set_defaults_from_project(self):
        """Get the global/default tempo and time signature from project"""
        # Get the tempo at time 0 (which is the global tempo if no markers)
        tempo_info = RPR_TimeMap_GetMeasureInfo(0, 0, 0, 0, 0, 0, 0)
        if tempo_info[0]:  # retval
            self.default_tempo = tempo_info[7]  # tempo
            self.default_time_sig = (tempo_info[5], tempo_info[6])  # numerator, denominator
    
    def add_tempo(self, time: float, bpm: float):
        """Add a tempo marker"""
        if bpm > 0:  # Only add valid tempos
            self.tempo_markers.append((time, bpm))
    
    def add_time_signature(self, time: float, numerator: int, denominator: int):
        """Add a time signature marker"""
        if numerator > 0 and denominator > 0:
            self.time_sig_markers.append((time, numerator, denominator))
    
    def get_tempo_at_time(self, time: float) -> float:
        """Get tempo at a specific time"""
        if not self.tempo_markers:
            return self.default_tempo
        
        # Find the most recent tempo marker before or at this time
        applicable_tempo = self.default_tempo
        for marker_time, bpm in self.tempo_markers:
            if marker_time <= time:
                applicable_tempo = bpm
            else:
                break
        return applicable_tempo
    
    def get_time_signature_at_time(self, time: float) -> Tuple[int, int]:
        """Get time signature at a specific time"""
        if not self.time_sig_markers:
            return self.default_time_sig
        
        # Find the most recent time signature marker before or at this time
        applicable_sig = self.default_time_sig
        for marker_time, num, denom in self.time_sig_markers:
            if marker_time <= time:
                applicable_sig = (num, denom)
            else:
                break
        return applicable_sig
    
    def time_to_measure(self, time: float) -> int:
        """Convert time in seconds to measure number"""
        # Use REAPER's built-in function which handles tempo/time sig changes
        retval, proj, qn, qn_measure_start, qn_measure_end = RPR_TimeMap_QNToMeasures(
            0, RPR_TimeMap2_timeToQN(0, time), 0, 0
        )
        # REAPER returns 1-based measure index, convert to 0-based
        return max(0, retval - 1)
    
    def measure_to_time(self, measure: int) -> float:
        """Convert measure number to time in seconds"""
        # Get the measure info which includes the time at start of measure
        retval, proj, measure_num, qn_start, qn_end, timesig_num, timesig_denom, tempo = \
            RPR_TimeMap_GetMeasureInfo(0, measure, 0, 0, 0, 0, 0)
        return retval  # retval is the time in seconds at start of measure


class REAPERMIDIExtractor:
    """
    Main class for extracting MIDI from REAPER project
    """
    
    def __init__(self):
        self.tempo_map = TempoMap()
        self.time_selection: Optional[TimeSelection] = None
        self.song: Optional[MIDISongByMeasure] = None
        self.masks = MeasureMask()
        self.skips = MeasureMask()
        self.ignore = []
        self.autoregressive = []
        self.track_info_list: List[TrackInfo] = []
    
    def extract(self, mask_selected_items: bool = True, 
                mask_empty_items: bool = False) -> Tuple[MIDISongByMeasure, MeasureMask]:
        """
        Extract MIDI content from REAPER project
        
        Args:
            mask_selected_items: Mark selected MIDI items for masking
            mask_empty_items: Mark empty measures for masking
        
        Returns:
            Tuple of (MIDISongByMeasure, MeasureMask)
        """
        # Build tempo map FIRST (needed for time selection conversion)
        self._build_tempo_map()
        
        # Get time selection
        self.time_selection = self._get_time_selection()
        
        # Determine measure range from time selection
        if self.time_selection.has_selection:
            start_measure = self.time_selection.start_measure
            end_measure = self.time_selection.end_measure
        else:
            # No time selection - use entire project
            start_measure = 0
            end_measure = self._get_project_end_measure()
        
        # If no measures in range, return empty
        if end_measure <= start_measure:
            num_measures = 0
        else:
            num_measures = end_measure - start_measure
        
        # Get MIDI tracks with instrument info
        self.track_info_list = self._get_midi_tracks_with_info()
        num_tracks = len(self.track_info_list)
        
        # Initialize song structure
        self.song = MIDISongByMeasure(num_tracks, num_measures)
        self.song.set_track_info(self.track_info_list)
        
        # Extract MIDI from each track
        for track_idx, track_info in enumerate(self.track_info_list):
            self._extract_track_midi(track_info, track_idx, start_measure, end_measure,
                                    mask_selected_items, mask_empty_items)
        
        return self.song, self.masks, self.skips, self.ignore, self.autoregressive
    
    def _get_time_selection(self) -> TimeSelection:
        """Get current time selection in REAPER"""
        is_set, is_loop, start_time, end_time, allowautoseek = RPR_GetSet_LoopTimeRange(0, 0, 0, 0, 0)
        
        # Convert times to measures.
        # end_time typically lands exactly on a bar boundary (the START of the
        # next bar). Floating-point fuzz can push time_to_measure into the next
        # bar, giving an off-by-one extra measure. Step back by a tiny epsilon
        # so we resolve the LAST included bar, then +1 for exclusive end.
        EPS = 1e-6
        start_measure = self.tempo_map.time_to_measure(start_time) if start_time > 0 else 0
        if end_time > start_time:
            end_measure = self.tempo_map.time_to_measure(end_time - EPS) + 1
        else:
            end_measure = 0
        
        return TimeSelection(
            start_time=start_time,
            end_time=end_time,
            start_measure=start_measure,
            end_measure=end_measure
        )
    
    def _build_tempo_map(self):
        """Extract tempo and time signature information from project"""
        # First, get the global/default tempo and time signature
        self.tempo_map.set_defaults_from_project()
        
        # Then get all tempo/time sig markers (if any)
        num_tempo_markers = RPR_CountTempoTimeSigMarkers(0)
        for i in range(num_tempo_markers):
            marker_info = RPR_GetTempoTimeSigMarker(0, i, 0, 0, 0, 0, 0, 0, 0)
            if len(marker_info) < 8:
                raise RuntimeError(
                    f"Unexpected RPR_GetTempoTimeSigMarker result length: {len(marker_info)}"
                )

            retval = marker_info[0]
            timepos = marker_info[1]
            bpm = marker_info[4]
            timesig_num = marker_info[5]
            timesig_denom = marker_info[6]
            
            if retval:
                self.tempo_map.add_tempo(timepos, bpm)
                self.tempo_map.add_time_signature(timepos, timesig_num, timesig_denom)
    
    def _detect_instrument(self, track, track_name: str) -> int:
        """Detect instrument number. MIDI channel 9 notes mean drums (GM channel 10)."""
        num_items = RPR_CountTrackMediaItems(track)
        for j in range(num_items):
            item = RPR_GetTrackMediaItem(track, j)
            take = RPR_GetActiveTake(item)
            if not take or not RPR_TakeIsMIDI(take):
                continue
            retval, _, note_count, _, _ = RPR_MIDI_CountEvts(take, 0, 0, 0)
            for n in range(min(note_count, 32)):
                note_info = RPR_MIDI_GetNote(take, n, 0, 0, 0, 0, 0, 0, 0)
                if note_info[0] and note_info[7] == 9:
                    return 128
        return get_instrument_from_track_name(track_name)

    def _get_midi_tracks_with_info(self) -> List[TrackInfo]:
        """Get list of tracks that have at least one MIDI item (even if empty)."""
        track_info_list = []
        num_tracks = RPR_CountTracks(0)
        
        for i in range(num_tracks):
            track = RPR_GetTrack(0, i)
            
            # Include the track if it has at least one MIDI item (notes not required).
            # This ensures empty tracks selected for infill are present in the song dict.
            has_midi_item = False
            num_items = RPR_CountTrackMediaItems(track)
            
            for j in range(num_items):
                item = RPR_GetTrackMediaItem(track, j)
                take = RPR_GetActiveTake(item)
                
                if take and RPR_TakeIsMIDI(take):
                    has_midi_item = True
                    break
            
            if has_midi_item:
                # Get track name
                retval, track_obj, flags_out = RPR_GetTrackState(track, 0)
                track_name = retval if retval else f"Track {i+1}"

                # Detect instrument: MIDI channel 9 (GM drums) takes priority
                # over name-based heuristics, which are unreliable.
                instrument = self._detect_instrument(track, track_name)

                track_info = TrackInfo(
                    track_index=len(track_info_list),
                    track=track,
                    track_name=track_name,
                    instrument=instrument
                )
                track_info_list.append(track_info)
        
        return track_info_list
    
    def _get_project_end_measure(self) -> int:
        """Get the last measure with MIDI content in project"""
        project_length = RPR_GetProjectLength(0)
        return self.tempo_map.time_to_measure(project_length)
    
    def _extract_track_midi(self, track_info: TrackInfo, track_idx: int, start_measure: int, 
                           end_measure: int, mask_selected: bool, mask_empty: bool):
        """Extract MIDI from a single track"""
        track = track_info.track
        num_items = RPR_CountTrackMediaItems(track)
        
        # Build a map of which items are selected
        selected_items = set()
        for item_idx in range(num_items):
            item = RPR_GetTrackMediaItem(track, item_idx)
            if RPR_IsMediaItemSelected(item):
                selected_items.add(item)
        
        # Process each measure
        for measure_idx in range(start_measure, end_measure):
            measure_start_time = self.tempo_map.measure_to_time(measure_idx)
            measure_end_time = self.tempo_map.measure_to_time(measure_idx + 1)
            
            # Get tempo and time signature for this measure
            tempo = self.tempo_map.get_tempo_at_time(measure_start_time)
            time_sig = self.tempo_map.get_time_signature_at_time(measure_start_time)
            
            notes_in_measure = []
            has_selected_item_in_measure = False
            
            # Check all MIDI items in track
            for item_idx in range(num_items):
                item = RPR_GetTrackMediaItem(track, item_idx)
                take = RPR_GetActiveTake(item)
                
                if not take or not RPR_TakeIsMIDI(take):
                    continue
                
                # Get item time range
                item_start = RPR_GetMediaItemInfo_Value(item, "D_POSITION")
                item_length = RPR_GetMediaItemInfo_Value(item, "D_LENGTH")
                item_end = item_start + item_length
                
                # Check if item overlaps with this measure
                if item_end <= measure_start_time or item_start >= measure_end_time:
                    continue  # Item doesn't overlap this measure
                
                # Check if this item is selected
                if item in selected_items:
                    has_selected_item_in_measure = True
                
                # Extract notes from this item that fall in this measure
                notes = self._extract_notes_from_item(take, measure_start_time, measure_end_time)
                notes_in_measure.extend(notes)
            
            # Create measure object
            measure = MIDIMeasure(
                measure_number=measure_idx,
                track_index=track_idx,
                instrument=track_info.instrument,
                notes=notes_in_measure,
                start_time=measure_start_time,
                end_time=measure_end_time,
                tempo=tempo,
                time_signature=time_sig
            )
            
            # Set measure in song
            relative_measure_idx = measure_idx - start_measure
            self.song.set_measure(track_idx, relative_measure_idx, measure)
            
            # Add to mask if needed
            # Only mask if there's a selected item overlapping this specific measure
            if mask_selected and has_selected_item_in_measure:
                self.masks.add_mask(track_idx, relative_measure_idx)
            elif mask_empty and measure.is_empty:
                self.masks.add_mask(track_idx, relative_measure_idx)
    
    def _extract_notes_from_item(self, take, measure_start: float, 
                                 measure_end: float) -> List[MIDINote]:
        """Extract MIDI notes from a take that fall within the measure"""
        notes = []
        
        # Get item position and offset
        item = RPR_GetMediaItemTake_Item(take)
        item_pos = RPR_GetMediaItemInfo_Value(item, "D_POSITION")
        take_offset = RPR_GetMediaItemTakeInfo_Value(take, "D_STARTOFFS")
        
        # Get number of notes
        retval, take_obj, note_count, cc_count, text_count = RPR_MIDI_CountEvts(take, 0, 0, 0)
        
        for note_idx in range(note_count):
            retval, take_obj, idx, selected, muted, start_ppq, end_ppq, chan, pitch, vel = \
                RPR_MIDI_GetNote(take, note_idx, 0, 0, 0, 0, 0, 0, 0)
            
            if not retval or muted:
                continue
            
            # Convert PPQ to project time
            note_start_time = RPR_MIDI_GetProjTimeFromPPQPos(take, start_ppq)
            note_end_time = RPR_MIDI_GetProjTimeFromPPQPos(take, end_ppq)
            
            # Check if note overlaps with measure
            if note_end_time > measure_start and note_start_time < measure_end:
                # Clip note to measure boundaries
                clipped_start = max(note_start_time, measure_start)
                clipped_end = min(note_end_time, measure_end)
                
                # Store times relative to measure start
                note = MIDINote(
                    pitch=pitch,
                    velocity=vel,
                    start_time=clipped_start - measure_start,
                    end_time=clipped_end - measure_start
                )
                notes.append(note)
        
        return notes


class REAPERMIDIWriter:
    """
    Writes MIDI data back to REAPER project
    """
    
    def __init__(self, tempo_map: TempoMap):
        self.tempo_map = tempo_map
    
    def write_to_project(self, song: MIDISongByMeasure, 
                        notes_are_selected: bool = True,
                        delete_existing: bool = True):
        """
        Write MIDI data to REAPER project
        
        Args:
            song: MIDISongByMeasure object with MIDI content to write
            notes_are_selected: Whether newly created notes should be selected
            delete_existing: Whether to delete existing notes in the measures being written
        """
        # Group measures by track for efficient writing
        measures_by_track = {}
        
        for track_idx in range(song.num_tracks):
            track_info = song.get_track_info(track_idx)
            if not track_info:
                continue
            
            measures_for_track = []
            for measure_idx in range(song.num_measures):
                measure = song.get_measure(track_idx, measure_idx)
                if measure and not measure.is_empty:
                    measures_for_track.append(measure)
            
            if measures_for_track:
                measures_by_track[track_info] = measures_for_track
        
        # Write to each track
        for track_info, measures in measures_by_track.items():
            self._write_track_measures(track_info, measures, notes_are_selected, delete_existing)
    
    def _write_track_measures(self, track_info: TrackInfo, measures: List[MIDIMeasure],
                              notes_are_selected: bool, delete_existing: bool):
        """Write measures to a specific track"""
        track = track_info.track
        
        # Group measures by which MIDI item they belong to
        # Each measure might be in a different split item
        measures_by_take = {}
        
        for measure in measures:
            # Find the MIDI take for THIS specific measure
            take = self._get_midi_take_for_measure(track, measure)
            
            if take:
                if take not in measures_by_take:
                    measures_by_take[take] = []
                measures_by_take[take].append(measure)
            else:
                print(f"Warning: Could not find MIDI take for track {track_info.track_name}, measure {measure.measure_number}")
        
        # Process each take separately
        for take, take_measures in measures_by_take.items():
            if delete_existing:
                # Delete notes from all measures in this take first
                for measure in take_measures:
                    self._delete_notes_in_measure(take, measure)
            
            # Then write all new notes to this take
            for measure in take_measures:
                self._write_measure_notes(take, measure, notes_are_selected)
            
            # Sort MIDI events for this take
            RPR_MIDI_Sort(take)
    
    def _get_midi_take_for_measure(self, track, measure: MIDIMeasure):
        """Get the MIDI take that contains this specific measure"""
        num_items = RPR_CountTrackMediaItems(track)
        
        measure_start = measure.start_time
        measure_end = measure.end_time
        
        # Find MIDI item that overlaps this measure
        for i in range(num_items):
            item = RPR_GetTrackMediaItem(track, i)
            item_pos = RPR_GetMediaItemInfo_Value(item, "D_POSITION")
            item_len = RPR_GetMediaItemInfo_Value(item, "D_LENGTH")
            item_end = item_pos + item_len
            
            # Check if this item overlaps this specific measure
            if item_end > measure_start and item_pos < measure_end:
                take = RPR_GetActiveTake(item)
                if take and RPR_TakeIsMIDI(take):
                    return take
        
        return None
    
    def _get_or_create_midi_take(self, track, measures: List[MIDIMeasure]):
        """Get existing MIDI take or create a new one covering the measure range"""
        if not measures:
            return None
        
        # Find the time range we need to cover
        start_time = min(m.start_time for m in measures)
        end_time = max(m.end_time for m in measures)
        
        # Check if there's already a MIDI item that overlaps this range
        # We'll use the FIRST overlapping MIDI item we find
        num_items = RPR_CountTrackMediaItems(track)
        
        for i in range(num_items):
            item = RPR_GetTrackMediaItem(track, i)
            item_pos = RPR_GetMediaItemInfo_Value(item, "D_POSITION")
            item_len = RPR_GetMediaItemInfo_Value(item, "D_LENGTH")
            item_end = item_pos + item_len
            
            # Check if this item overlaps our range (not just contains it)
            if item_end > start_time and item_pos < end_time:
                take = RPR_GetActiveTake(item)
                if take and RPR_TakeIsMIDI(take):
                    # Found an existing MIDI item that overlaps - use it
                    return take
        
        # No existing item found - create a new one
        # Note: This should rarely happen if you're modifying existing items
        try:
            item = RPR_CreateNewMIDIItemInProj(track, start_time, end_time, False)
            if item:
                return RPR_GetActiveTake(item)
        except:
            # Fallback: use AddMediaItemToTrack + AddTakeToMediaItem
            retval, proj, track_obj, start, end = RPR_AddMediaItemToTrack(track, 0, start_time, end_time, 0)
            if retval:
                take = RPR_AddTakeToMediaItem(retval)
                return take
        
        return None
    
    def _delete_notes_in_measure(self, take, measure: MIDIMeasure):
        """Delete existing notes in a measure's time range"""
        retval, take_obj, num_notes, cc_count, text_count = RPR_MIDI_CountEvts(take, 0, 0, 0)
        
        # Convert measure time range to PPQ
        measure_start_ppq = RPR_MIDI_GetPPQPosFromProjTime(take, measure.start_time)
        measure_end_ppq = RPR_MIDI_GetPPQPosFromProjTime(take, measure.end_time)
        
        # Delete notes backwards to avoid index shifting issues
        # We need to check if note OVERLAPS with measure, not just starts in it
        for note_idx in range(num_notes - 1, -1, -1):
            retval, take_obj, idx, selected, muted, start_ppq, end_ppq, chan, pitch, vel = \
                RPR_MIDI_GetNote(take, note_idx, 0, 0, 0, 0, 0, 0, 0)
            
            if retval:
                # Delete if note overlaps with measure
                # A note overlaps if: note_end > measure_start AND note_start < measure_end
                if end_ppq > measure_start_ppq and start_ppq < measure_end_ppq:
                    RPR_MIDI_DeleteNote(take, note_idx)
    
    def _write_measure_notes(self, take, measure: MIDIMeasure, notes_are_selected: bool):
        """Write notes from a measure to a take"""
        if not measure.notes:
            return
        
        # Get item position
        item = RPR_GetMediaItemTake_Item(take)
        item_pos = RPR_GetMediaItemInfo_Value(item, "D_POSITION")
        
        # Insert each note
        for note in measure.notes:
            # Convert measure-relative times to project times
            note_start_proj = measure.start_time + note.start_time
            note_end_proj = measure.start_time + note.end_time
            
            # Convert project times to PPQ
            start_ppq = RPR_MIDI_GetPPQPosFromProjTime(take, note_start_proj)
            end_ppq = RPR_MIDI_GetPPQPosFromProjTime(take, note_end_proj)
            
            # Insert note
            # channel = 0 for non-drums, 9 for drums (instrument 128)
            channel = 9 if measure.instrument == 128 else 0
            
            RPR_MIDI_InsertNote(
                take,
                notes_are_selected,  # selected
                False,              # muted
                int(start_ppq),
                int(end_ppq),
                channel,
                note.pitch,
                note.velocity,
                True                # no sort (we'll sort at the end)
            )


class MIDIExtractionResult:
    """Result of MIDI extraction"""
    
    def __init__(self, song: MIDISongByMeasure, masks: MeasureMask,
                 skips: MeasureMask, ignore : list, autoregressive : list,
                 start_measure: int, end_measure: int,
                 time_selection: TimeSelection, tempo_map: 'TempoMap'):
        self.song = song
        self.masks = masks
        self.skips = skips
        self.ignore = ignore
        self.autoregressive = autoregressive
        self.start_measure = start_measure
        self.end_measure = end_measure
        self.time_selection = time_selection
        self.tempo_map = tempo_map  # Needed for writing back
    
    @property
    def has_selection(self) -> bool:
        return self.time_selection.has_selection
    
    @property
    def num_masked_measures(self) -> int:
        return self.masks.count
    
    def write_to_project(self, notes_are_selected: bool = True, delete_existing: bool = True):
        """
        Write the MIDI data back to REAPER project
        
        Args:
            notes_are_selected: Whether newly created notes should be selected
            delete_existing: Whether to delete existing notes in the measures being written
        """
        writer = REAPERMIDIWriter(self.tempo_map)
        writer.write_to_project(self.song, notes_are_selected, delete_existing)


def extract_midi_for_mmm(mask_selected_items: bool = True,
                        mask_empty_items: bool = False) -> MIDIExtractionResult:
    """
    Main entry point for MIDI extraction
    
    Args:
        mask_selected_items: Mark selected MIDI items for infill
        mask_empty_items: Mark empty measures for infill
    
    Returns:
        MIDIExtractionResult containing song structure and masks
    """
    extractor = REAPERMIDIExtractor()
    song, masks, skips, ignore, autoregressive = extractor.extract(mask_selected_items, mask_empty_items)
    
    return MIDIExtractionResult(
        song=song,
        masks=masks,
        skips=skips,
        ignore=ignore,
        autoregressive=autoregressive,
        start_measure=extractor.time_selection.start_measure,
        end_measure=extractor.time_selection.end_measure,
        time_selection=extractor.time_selection,
        tempo_map=extractor.tempo_map
    )


def write_midi_to_project(song: MIDISongByMeasure, tempo_map: TempoMap,
                         notes_are_selected: bool = True, delete_existing: bool = True):
    """
    Standalone function to write MIDI back to REAPER
    
    Args:
        song: MIDISongByMeasure object with MIDI content
        tempo_map: TempoMap for time conversions
        notes_are_selected: Whether newly created notes should be selected
        delete_existing: Whether to delete existing notes in the measures being written
    """
    writer = REAPERMIDIWriter(tempo_map)
    writer.write_to_project(song, notes_are_selected, delete_existing)
