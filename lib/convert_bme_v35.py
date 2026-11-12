#!/usr/bin/env python3
"""Convert classic BMS/BME 5-key playable-lane onset grids to v3.5 PIU source JSON.
Keeps exact rational beat positions, LNTYPE1 pairs, source attack multiplicity.
Does not synthesize key sounds. A pre-mixed audio recording must be supplied.
"""
import argparse, collections, json, re, zipfile
from fractions import Fraction as F
from pathlib import Path

REGEX=re.compile(r'^#(\d{3})([A-Z0-9]{2}):([A-Z0-9]+)\s*$', re.I)
TAPS={'11','12','14','18','19'}
HOLDS={'51','52','54','58','59'}

def parse_bme(raw:bytes, music='Yo_Creo_Que_Si.ogg'):
    decoded=None
    for encoding in ('utf-8-sig','cp932','latin1'):
        try:decoded=raw.decode(encoding);break
        except UnicodeDecodeError:pass
    assert decoded is not None
    headers={};channel_records=[];bar_multiplier={};unsupported=[]
    for line in decoded.splitlines():
        line=line.strip()
        if not line.startswith('#'):continue
        match=REGEX.fullmatch(line)
        if match:
            m,ch,blob=match.groups();m=int(m);ch=ch.upper()
            if ch=='02':
                try:bar_multiplier[m]=F(blob)
                except Exception:unsupported.append({'measure':m,'channel':ch,'value':blob})
                continue
            channel_records.append((m,ch,blob))
        else:
            k=re.match(r'^#([A-Z0-9]+)\s+(.+)$',line,re.I)
            if k:headers[k.group(1).upper()]=k.group(2).strip()
    if bar_multiplier:raise NotImplementedError('Variable-length measures require cumulative beat offsets')
    timing_ch={ch for _,ch,_ in channel_records if ch in ('03','08','09')}
    if timing_ch:raise NotImplementedError('BMS has timing changes: '+','.join(sorted(timing_ch)))
    if any(k.startswith('BPM') and k!='BPM' for k in headers):
        raise NotImplementedError('Extended BPM table present')
    taps=collections.defaultdict(set)
    holds_raw=collections.defaultdict(list)
    diagnostics={'tap_tokens':0,'ln_tokens':0,'audio_channels':0,'unknown_playable_channels':[]}
    for m,ch,blob in channel_records:
        if len(blob)%2:raise ValueError(f'Odd channel data length at measure {m} ch {ch}')
        if ch=='01':diagnostics['audio_channels']+=1
        if ch not in TAPS|HOLDS:
            if ch[0] in ('1','2','5','6') and ch not in ('01',):
                diagnostics['unknown_playable_channels'].append(ch)
            continue
        div=len(blob)//2
        for i in range(div):
            key=blob[2*i:2*i+2].upper()
            if key=='00':continue
            beat=F(m*4)+F(4*i,div)
            if ch in TAPS:
                taps[beat].add(ch);diagnostics['tap_tokens']+=1
            else:
                holds_raw[ch].append((beat,key));diagnostics['ln_tokens']+=1
    intervals=[]
    for lane,points in sorted(holds_raw.items()):
        points.sort()
        if len(points)%2:raise ValueError(f'Unpaired LN tokens in {lane}: {len(points)}')
        for j in range(0,len(points),2):
            a,ka=points[j];b,kb=points[j+1]
            if b<=a:raise ValueError('Invalid LN order')
            intervals.append((a,b,lane,ka,kb))
    events={beat:{'hits':len(lanes),'tap_lanes':sorted(lanes),'hold_ends':[], 'hold_lanes':[]} for beat,lanes in taps.items()}
    for start,end,lane,_,_ in intervals:
        e=events.setdefault(start,{'hits':0,'tap_lanes':[],'hold_ends':[],'hold_lanes':[]})
        e['hits']+=1;e['hold_ends'].append(str(end));e['hold_lanes'].append(lane)
    result=[]
    for beat,e in sorted(events.items()):
        r={'beat':str(beat),'source_hits':max(1,e['hits']),'tap_lanes':e['tap_lanes']}
        if e['hold_ends']:
            r['hold_ends']=e['hold_ends'];r['hold_lanes']=e['hold_lanes']
        result.append(r)
    diagnostics.update({'unique_onsets':len(events),'hold_heads':len(intervals),'first_beat':str(min(events)),
                        'last_beat':str(max(events)),'bpm':float(headers['BPM']),
                        'notes_ordinary':sum(len(x) for x in taps.values()),
                        'tap_count_plus_holds':sum(len(x) for x in taps.values())+len(intervals),
                        'hold_intervals':[{'start':str(a),'end':str(b),'lane':lane} for a,b,lane,_,_ in intervals],
                        'bms_channels':sorted(set(ch for _,ch,_ in channel_records)),
                        'unique_note_lanes':sorted(TAPS), 'source_lane_count':5})
    if diagnostics['unknown_playable_channels']:raise ValueError('Unknown playable channels '+str(diagnostics['unknown_playable_channels']))
    return {'title':'Yo Creo Que Si','artist':headers.get('ARTIST','makou'), 'bpm':float(headers['BPM']),
            'offset':0.0,'music':music,'genre':headers.get('GENRE',''),'events':result,
            'source':'BMS/BME original 5-button input','source_chart':headers.get('TITLE',''),
            'source_hold_heads':len(intervals),'source_note_attacks':diagnostics['tap_count_plus_holds'],
            'adapter_notes':'BMS LNTYPE1 long-note endpoints paired per 5-key lane; audio pre-mixed; exact rational beats'},diagnostics

def main():
    p=argparse.ArgumentParser();p.add_argument('archive');p.add_argument('--out',default='yocreo_events.json');p.add_argument('--music',default='yocreo.wav');p.add_argument('--offset',type=float,default=0.0,help='StepMania SSC #OFFSET in seconds, calibrated to THIS audio');o=p.parse_args()
    with zipfile.ZipFile(o.archive) as z:
        bmes=[n for n in z.namelist() if Path(n).suffix.lower() in ('.bms','.bme','.bml')]
        if len(bmes)!=1:raise ValueError('Expected one BMS chart: '+str(bmes))
        src,diagnostics=parse_bme(z.read(bmes[0]),music=o.music)
    src['offset']=o.offset
    Path(o.out).write_text(json.dumps(src,indent=2,ensure_ascii=False),encoding='utf8')
    Path(o.out).with_suffix('.analysis.json').write_text(json.dumps(diagnostics,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in diagnostics.items() if k!='hold_intervals'},indent=2))
if __name__=='__main__':main()
