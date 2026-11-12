"""Exact constant-BPM BMS/BME 5-key -> native-compatible input grid.

This is deliberately a *mapped source* adapter: only original BMS note heads,
chords and hold intervals enter the composer. It never discovers new audio notes.
Unsupported timing branches are rejected rather than silently approximated.
"""
from __future__ import annotations
from collections import Counter
from fractions import Fraction as F
import math,re,hashlib
from pathlib import Path
from . import nx20
from .sources import events_of

BMS_KEYS={'11':0,'12':1,'14':2,'18':3,'19':4}
HOLD_KEYS={'51':0,'52':1,'54':2,'58':3,'59':4}


def guard_bms(raw):
    text=raw.decode('latin1')
    branch=re.findall(r'^\s*#(RANDOM|SETRANDOM|IF|ELSE|ELSEIF|ENDIF|ENDRANDOM|SWITCH|CASE|DEF|ENDSW|LNOBJ)\b',text,re.M|re.I)
    if branch:raise ValueError('BMS uses unsupported branching/LNOBJ: '+','.join(branch))
    if re.search(r'^\s*#LNTYPE\s+(?!1\s*$)\S+',text,re.M|re.I):
        raise ValueError('Only BMS LNTYPE 1 is supported')
    if re.search(r'^\s*#\d{3}(?:02|03|08|09)\s*:',text,re.M|re.I):
        raise ValueError('Variable measure length, BPM changes and STOP not supported by BMS adapter')
    if re.search(r'^\s*#BPM[0-9A-Z]{2}\s+',text,re.M|re.I):
        raise ValueError('Extended BPM table unsupported')
    if not re.search(r'^\s*#BPM\s+\d',text,re.M|re.I):
        raise ValueError('BMS constant #BPM required')


def adapt_bytes(raw, *, offset=0.0):
    """Return (NX-like source, audit, metadata). Offset follows StepMania convention."""
    from convert_bme_v35 import parse_bme
    guard_bms(raw)
    meta,diag=parse_bme(raw,music='original_audio.wav')
    bpm=float(meta['bpm'])
    if not math.isfinite(bpm) or not 1<=bpm<=1000:raise ValueError('Invalid BPM')
    offset=float(offset)
    if not math.isfinite(offset) or abs(offset)>120:raise ValueError('Invalid offset')
    points=set([F(0)]);heads={};intervals=[]
    for event in meta['events']:
        beat=F(event['beat']);points.add(beat)
        for lane in event.get('tap_lanes',[]):
            if lane not in BMS_KEYS:raise ValueError(f'Unsupported playable tap lane {lane}')
            key=(beat,BMS_KEYS[lane]);
            if key in heads:raise ValueError(f'Duplicate source key at {key}')
            heads[key]=nx20.TAP
        hold_lanes=event.get('hold_lanes',[])
        hold_ends=event.get('hold_ends',[])
        if len(hold_lanes)!=len(hold_ends):raise ValueError('Mismatched BMS hold lanes and tails')
        for lane,tail in zip(hold_lanes,hold_ends):
            if lane not in HOLD_KEYS:raise ValueError(f'Unsupported hold lane {lane}')
            end=F(tail);points.add(end)
            if end<=beat:raise ValueError('Nonpositive hold')
            key=(beat,HOLD_KEYS[lane]);
            if key in heads:raise ValueError(f'Tap/hold overlap at source key {key}')
            heads[key]=nx20.HOLD_START;intervals.append((beat,end,HOLD_KEYS[lane]))
    if not heads:raise ValueError('No BMS source note heads')
    # This stage cannot invent quantization or shorten holds. If a source uses
    # finer than 1/24 beat, it remains unsupported in this research engine.
    rpb=1
    for b in points:rpb=math.lcm(rpb,b.denominator)
    if rpb>24:raise ValueError(f'BMS grid requires {rpb} rows per beat (>24); not quantized')
    finalbeat=F(4*math.ceil((max(points)+4)/4))
    count=int(finalbeat*rpb)
    if count<1 or count>500000:raise ValueError('BMS chart duration exceeds research backend bounds')
    flat=[[0]*5 for _ in range(count)]
    for (beat,lane),kind in heads.items():
        idx=int(beat*rpb)
        if flat[idx][lane]:raise ValueError(f'Overlapping BMS head at {beat}/{lane}')
        flat[idx][lane]=kind
    for start,end,lane in intervals:
        i=int(start*rpb);j=int(end*rpb)
        for tick in range(i+1,j):
            if flat[tick][lane]:raise ValueError(f'Overlapping BMS body at {tick}/{lane}')
            flat[tick][lane]=nx20.HOLD_BODY
        if flat[j][lane]:raise ValueError(f'Overlapping BMS tail at {end}/{lane}')
        flat[j][lane]=nx20.HOLD_END
    source={'cols':5,'unk':0,'tags':[(1000,1),(1001,1)],
            'splits':[{'head':(0,0,1,-offset*1000.,bpm,1./rpb,0.,1.,0x400|rpb,0,count),
                       'rows':[tuple(r) if any(r) else None for r in flat]}], 'pool':b''}
    source=nx20.parse(nx20.build(source))
    timeline,events=events_of(source)
    got_heads=sum(len(e['lanes']) for e in events)
    if got_heads!=len(heads) or sum(len(e['holds']) for e in events)!=len(intervals):
        raise ValueError('BMS head/hold conservation verification failed')
    mismatch=max((abs(e['ms']-(-offset*1000.+e['beat']*60000./bpm)) for e in events),default=0.)
    if mismatch>=.1:raise ValueError('BMS source/NX clock drifts by >=0.1ms')
    audit={'format':'BMS/BME mapped five keys; LNTYPE 1; constant BPM',
           'sha256':hashlib.sha256(raw).hexdigest(),
           'source_onsets':len(events),'source_heads':len(heads),'source_holds':len(intervals),
           'rows_per_beat':rpb,'bpm':bpm,'offset_seconds':offset,
           'max_abs_nx_timing_error_ms':mismatch,
           'unsupported_constructs_rejected':True,
           'audio_beat_calibration_verified':False,
           'source_head_lanes':['11','12','14','18','19']}
    return source,audit,meta
