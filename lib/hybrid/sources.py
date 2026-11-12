"""Exact rational source clocks; no grace folding or shortened hold tails."""
from __future__ import annotations
from fractions import Fraction as F
from collections import defaultdict
from pathlib import Path
import math, hashlib, json, copy
from . import nx20

TAP,HEAD,BODY,TAIL=0x343,0x357,0x35B,0x35F

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def timeline(nx):
    out=[];beat=0.
    for k,s in enumerate(nx['splits']):
        h=s['head'];bpm=float(h[4]);rpb=int(h[8])&255
        if not math.isfinite(bpm) or bpm<=0 or not 1<=rpb<=192:raise ValueError('invalid source timing')
        beat+=float(h[6])*bpm/60000
        for row in range(len(s['rows'])):out.append((beat+row/rpb,float(h[3])+row*60000/bpm/rpb,k,row))
        beat+=len(s['rows'])/rpb
    return out

def events_of(nx):
    tl=timeline(nx);events={};open_holds={}
    for i,(bt,ms,k,r) in enumerate(tl):
        cells=nx['splits'][k]['rows'][r]
        if cells is None:continue
        for lane,value in enumerate(cells):
            kind=value&255
            if not value:continue
            if kind in (0x43,0x57):
                if lane in open_holds:raise ValueError(f'source overlap in lane{lane} row{i}')
                e=events.setdefault(i,{'index':i,'beat':bt,'ms':ms,'lanes':[],'holds':[],
                                      'hold_ends_ms':{},'hold_ends_beat':{}})
                e['lanes'].append(lane)
                if kind==0x57:open_holds[lane]=i
            elif kind==0x5F:
                if lane not in open_holds:raise ValueError(f'orphan source hold tail lane{lane} row{i}')
                start=open_holds.pop(lane)
                if ms<=tl[start][1]:raise ValueError('nonpositive source hold')
                events[start]['holds'].append((i,lane));events[start]['hold_ends_ms'][i]=ms
                events[start]['hold_ends_beat'][i]=bt
            elif kind==0x5B:
                if lane not in open_holds:raise ValueError('orphan source hold body')
            else:raise ValueError(f'unsupported source cell{value:#x}; omission requires external provenance ledger')
    if open_holds:raise ValueError(f'unclosed source holds {open_holds}')
    es=list(events.values())
    if any(b['ms']<=a['ms'] for a,b in zip(es,es[1:])):raise ValueError('non-increasing source attack clock')
    return tl,es

def respect(path,keys):
    from .respect_chart import parse,tick_seconds
    raw=Path(path).read_bytes();c=parse(raw,Path(path).stem);tpb=F(str(c['ticks_per_beat']))
    if keys not in (4,5,6,8):raise ValueError('explicit RESPECT key mode required')
    notes=[];points={F(0)};classification=[]
    for lane,track in enumerate(c['tracks'][3:3+keys]):
        for n in track['notes']:
            beat=F(n['tick'])/tpb
            # Native six-tick duration is the keyboard tap envelope, not a hold.
            # This is source-format semantics, recorded per input note.
            held=n['length']>6;end=F(n['tick']+n['length'])/tpb if held else None
            notes.append((beat,end,lane,n));points.add(beat)
            if held:points.add(end)
            classification.append({'tick':n['tick'],'lane':lane,'length':n['length'],
                'kind':'hold' if held else 'tap_envelope','native_sound':n['sound']})
    if not notes:raise ValueError('source has no playable notes')
    bpms=[(F(t)/tpb,float(v)) for t,v in c['bpms']]
    points.update(b for b,_ in bpms)
    rpb=1
    for b in points:rpb=math.lcm(rpb,b.denominator)
    if rpb>192:raise ValueError(f'source rational grid exceeds supported research input: {rpb}')
    end=F(math.ceil(max(max(points)+4,F(c['end_tick'])/tpb+4)))
    # Local phase changes retain off-phase original heads and tails. The residual
    # is an explicit positive Delay, not an early release or a snapped note.
    bounds=sorted(points|{end})
    cells={};intervals=[]
    for a,b,l,n in notes:
        if (a,l) in cells:raise ValueError(f'duplicate native head {a}/{l}')
        cells[a,l]=HEAD if b is not None else TAP
        if b is not None:intervals.append((a,b,l))
    for a,b,l in intervals:
        if (b,l) in cells:raise ValueError(f'hold tail/source head collide at {b}/{l}')
        cells[b,l]=TAIL
    splits=[];previous=0.
    for a,b in zip(bounds,bounds[1:]):
        delta=b-a
        active=any(x<=a<y for x,y,_ in intervals)
        local_rpb=24 if active else next((v for v in range(1,25) if delta*v>=1),24)
        if any(at==b for at,_ in bpms[1:]):
            exact=[v for v in range(1,25) if (delta*v).denominator==1]
            if not exact:raise ValueError('BPM boundary cannot preserve exact beat phase under24ticks')
            local_rpb=min(exact)
        if delta*local_rpb<1:raise ValueError(f'Native boundary {a}->{b} is closer than1/24 beat; exact export blocked')
        count=int(delta*local_rpb);bpm=next(v for at,v in reversed(bpms) if at<=a)
        ms=tick_seconds(c,float(a*tpb))*1000;delay=ms-previous
        if delay<-.00001:raise ValueError('source serializer would create a negative Delay')
        rows=[]
        for j in range(count):
            beat=a+F(j,local_rpb);row=[cells.get((beat,l),0) for l in range(max(5,keys))]
            for x,y,l in intervals:
                if x<beat<y:
                    if row[l]:raise ValueError(f'overlapping native hold at {beat}/{l}')
                    row[l]=BODY
            rows.append(tuple(row))
        splits.append({'head':(0,0,1,ms,bpm,1/local_rpb,delay,1.,0x400|local_rpb,0,count),
                       'rows':[r if any(r) else None for r in rows]})
        previous=ms+count*60000/bpm/local_rpb
    source={'cols':max(5,keys),'unk':0,'tags':[(1000,1),(1001,1)],'splits':splits,'pool':b''}
    source=nx20.parse(nx20.build(source));tl,events=events_of(source)
    original=sorted(tick_seconds(c,n['tick'])*1000 for _,_,_,n in notes)
    actual=sorted(e['ms'] for e in events for _ in e['lanes'])
    native_beats=sorted(float(a) for a,_,_,_ in notes)
    actual_beats=sorted(e['beat'] for e in events for _ in e['lanes'])
    tails=sorted(tick_seconds(c,n['tick']+n['length'])*1000 for _,end,_,n in notes if end is not None)
    out_tails=sorted(tl[end][1] for e in events for end,_ in e['holds'])
    error=max([abs(a-b) for a,b in zip(original,actual)]+[abs(a-b) for a,b in zip(tails,out_tails)]+[0])
    if len(original)!=len(actual) or len(tails)!=len(out_tails) or error>=.1:raise ValueError('original source clock check failed')
    beat_error=max([abs(a-b) for a,b in zip(native_beats,actual_beats)]+[0])
    if beat_error>=1e-5:raise ValueError(f'original musical beat phase changed {beat_error}')
    return source,{'source_path':str(Path(path).resolve()),'source_sha256':hashlib.sha256(raw).hexdigest(),
        'format':'RESPECT native TextAsset','keys':keys,'original_global_rational_grid':rpb,
        'grid_rpb':max(s['head'][8]&255 for s in source['splits']),'original_heads':len(notes),
        'original_holds':len(intervals),'original_onsets':len(events),'original_clock_error_ms':error,
        'original_beat_phase_error':beat_error,
        'offset_seconds':0.,'microtiming_folded':False,'hold_tails_shortened':False,
        'classification':classification,'timing':bpms_as_json(bpms)}

def bpms_as_json(bpms):return [{'beat':str(b),'bpm':v} for b,v in bpms]

def render(source,plan,columns,level):
    nx=copy.deepcopy(source);tl=timeline(source);nx['cols']=columns
    flat=[[0]*columns for _ in tl]
    for e in plan:
        for lane,foot,end in e['actions']:
            start=e['index']
            if end<0:
                if flat[start][lane]:raise ValueError('overwriting a chart cell')
                flat[start][lane]=TAP
            else:
                if end<=start or any(flat[j][lane] for j in range(start,end+1)):raise ValueError('overlapping/invalid output hold')
                flat[start][lane]=HEAD
                for j in range(start+1,end):flat[j][lane]=BODY
                flat[end][lane]=TAIL
    for row,(_,_,k,r) in zip(flat,tl):nx['splits'][k]['rows'][r]=tuple(row) if any(row) else None
    # v363: PRIME needs <=24 rows/beat. Fine source grids are reduced only when
    # every head/tap/tail of the OUTPUT lies on the coarser grid (lossless).
    for si,s in enumerate(nx['splits']):
        h=list(s['head']);rpb=h[8]&255
        if rpb<=24:continue
        for f in range(2,rpb+1):
            if rpb%f or rpb//f>24:continue
            cut=len(s['rows'])%f   # row count must divide: trim empty trailing rows, or pad the last split (each split has its own start time)
            if cut and not any(s['rows'][-cut:]):s['rows']=list(s['rows'][:-cut])
            elif cut and not any(any(t['rows']) for t in nx['splits'][si+1:]):s['rows']=list(s['rows'])+[None]*(f-cut)   # nothing after it can shift
            elif cut:continue
            if all(i%f==0 or not row or all((v&255) in (0,BODY&255) for v in row) for i,row in enumerate(s['rows'])):
                s['rows']=s['rows'][::f];h[5]=h[5]*f;h[8]=(h[8]&~255)|(rpb//f);h[10]=len(s['rows']);s['head']=tuple(h);break
        else:raise ValueError('exact source requires >24 rows/beat; no grace folding, quantization, or early hold release allowed')
    nx['tags']=[(k,v) for k,v in nx['tags'] if k not in (1000,1001)]+[(1000,1),(1001,level)]
    return nx20.parse(nx20.build(nx))

def ssc_text(source,charts,title,artist,music='audio.ogg'):
    tl=timeline(source);offset=-tl[0][1]/1000;bpms=[];last_bpm=None
    exact=lambda b:F(b).limit_denominator(192)
    for bt,ms,k,r in tl:
        h=source['splits'][k]['head']
        if r==0 and h[4]!=last_bpm:
            bpms.append(f"{float(exact(bt)):.12g}={h[4]:.12g}");last_bpm=h[4]
    clean=lambda s:str(s).replace(';',',').replace('#','').replace('\n',' ')
    text=f"#TITLE:{clean(title)};\n#ARTIST:{clean(artist)};\n#MUSIC:{music};\n#OFFSET:{offset:.12g};\n#BPMS:{','.join(bpms)};\n#DISPLAYBPM:{source['splits'][0]['head'][4]:.2f};\n"
    for level,tier,nx in charts:
        notes=defaultdict(dict)
        for (bt,ms,k,r) in tl:
            row=nx['splits'][k]['rows'][r]
            if row is None:continue
            for lane,v in enumerate(row):
                if v in (TAP,HEAD,TAIL):notes[exact(bt)][lane]={TAP:'1',HEAD:'2',TAIL:'3'}[v]
        count=int(max(notes)//4)+1;measures=[]
        for measure in range(count):
            entries=[(bt-measure*4,row) for bt,row in notes.items() if measure*4<=bt<(measure+1)*4]
            rpb=1
            for bt,_ in entries:rpb=math.lcm(rpb,bt.denominator)
            rows=[['0']*nx['cols'] for _ in range(rpb*4)]
            for bt,row in entries:
                for lane,v in row.items():rows[int(bt*rpb)][lane]=v
            measures.append('\n'.join(''.join(row) for row in rows))
        diff='Easy' if level<=9 else 'Medium' if level<=14 else 'Hard' if level<=18 else 'Challenge'
        text+=f"\n#NOTEDATA:;\n#STEPSTYPE:{'pump-single' if nx['cols']==5 else 'pump-double'};\n#DESCRIPTION:HYBRID_3.6.1_S{level}_{tier}_REVIEW;\n#DIFFICULTY:{diff};\n#METER:{level};\n#NOTES:\n"+',\n'.join(measures)+';\n'
    return text
