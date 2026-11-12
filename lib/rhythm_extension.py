"""Human-authorized, recorded beat subdivisions; original notes/holds stay exact.

This creates an INTERNAL reference grid with virtual source lanes, never an
installable Pump chart. The v3.6.2 solver still has to route every selected event
and its independent validator still has to approve the resulting five/ten lanes.
"""
import copy,math,hashlib,bisect
from collections import Counter
from pumpdoublify_adapter import sources,nx20

def signature(nx,original_columns=None):
    _,events=sources.events_of(nx);limit=nx['cols'] if original_columns is None else original_columns
    return Counter((lane,round(e['ms'],5),None if lane not in {l for _,l in e['holds']} else round(e['hold_ends_ms'][next(end for end,l in e['holds'] if l==lane)],5)) for e in events for lane in e['lanes'] if lane<limit)

def compare_original_clocks(source,augmented):
    def grouped(nx,limit):
        groups={}
        for (lane,start,end),count in signature(nx,limit).items():groups.setdefault((lane,end is not None),[]).extend([(start,end)]*count)
        return {key:sorted(values) for key,values in groups.items()}
    a=grouped(source,source['cols']);b=grouped(augmented,source['cols'])
    if set(a)!=set(b):raise ValueError('Original note/hold lane or kind changed')
    error=0.
    for key,values in a.items():
        if len(values)!=len(b[key]):raise ValueError('Original note/hold count changed')
        for (start,end),(other,tail) in zip(values,b[key]):
            error=max(error,abs(start-other),abs(end-tail) if end is not None else 0)
    if error>=.1:raise ValueError('Original head/tail clock changed by >=0.1ms')
    return error

def extend(source,target_row_nps,*,seed=362,subdivisions=4,avoid_added_windows=(),verify=True):
    if target_row_nps<=0 or subdivisions not in (1,2,4):raise ValueError('Positive density and musical subdivisions1/2/4 required')
    oldcols=source['cols'];result=copy.deepcopy(source);result['cols']=oldcols+4
    rebuilt=[];active=set();previous_end=0.
    for split in result['splits']:
        head=list(split['head']);rpb=int(head[8])&255
        if not 1<=rpb<=192:raise ValueError('invalid reference grid')
        groups=[]
        for original_index,row in enumerate(split['rows']):
            row=list(row) if row else [0]*oldcols
            for lane,v in enumerate(row):
                kind=v&255
                if kind in (0x57,0x5b):active.add(lane)
                elif kind==0x5f:active.discard(lane)
            # Retain the exact scoring grid while any original hold is active.
            # Only hold-free portions of ordinary splits can gain empty rows.
            # v363: fine (>24 tick) grids are kept exact and simply not subdivided
            factor=max(1,min(4,24//rpb)) if not active and tuple(head[:3])==(0,0,1) else 1
            if not groups or groups[-1][0]!=factor:groups.append((factor,original_index,[]))
            groups[-1][2].append(tuple(row+[0]*4) if any(row) else None)
        for group_index,(factor,start,rows) in enumerate(groups):
            newrows=[]
            for row in rows:newrows.extend([row]+[None]*(factor-1))
            h=list(head);h[3]=head[3]+start*60000/head[4]/rpb
            h[5]=head[5]/factor;h[8]=(int(head[8])&~255)|(rpb*factor);h[10]=len(newrows)
            h[6]=head[6] if group_index==0 else h[3]-previous_end
            rebuilt.append(dict(head=tuple(h),rows=newrows));previous_end=h[3]+len(newrows)*60000/h[4]/(rpb*factor)
    result['splits']=rebuilt
    # Re-serialize before clock checks, so all comparisons include actual float32.
    result=nx20.parse(nx20.build(result))
    clock_error=compare_original_clocks(source,result) if verify else None
    tl,events=sources.events_of(result)
    if not events:raise ValueError('Cannot infer musical phrases from an empty chart')
    first,last=events[0]['ms'],events[-1]['ms'];duration=max(1.,(last-first)/1000)
    original_holds=[(e['ms'],e['hold_ends_ms'][end]) for e in events for end,_ in e['holds']]
    wanted=max(0,math.ceil(target_row_nps*duration)-len(events));times=sorted(e['ms'] for e in events)
    # No new notes in the intro/outro or in a long source rest. Candidate rows
    # must belong to an existing active eight-beat phrase and a regular grid.
    phase_origin=tl[0][0]
    active_phrases={int((e['beat']-phase_origin)//8) for e in events};candidates=[]
    beats=sorted(e['beat'] for e in events)
    for index,(beat,ms,k,r) in enumerate(tl):
        phase=beat-phase_origin
        if not first<ms<last or int(phase//8) not in active_phrases:continue
        # v363: float32 split delays drift the beat clock by ~1e-3 beat; 1e-4 rejected
        # almost every grid row. .03 of a subdivision is ~2-3ms.
        # Grid is local to the previous original attack (BPM changes drift phase).
        prior=bisect.bisect_right(beats,beat)-1
        rel=beat-beats[prior] if prior>=0 else phase
        if abs(rel*subdivisions-round(rel*subdivisions))>.03:continue
        if any(a<=ms<=b for a,b in avoid_added_windows):continue
        if sum(start<ms-.1 and ms<end-.1 for start,end in original_holds)>=2:continue
        if any(abs(ms-end)<95 for start,end in original_holds):continue
        pos=bisect.bisect_left(times,ms)
        if pos<len(times) and abs(times[pos]-ms)<.1:continue
        left=ms-times[pos-1] if pos else math.inf;right=times[pos]-ms if pos<len(times) else math.inf
        if min(left,right)<80 or min(left,right)>2000:continue
        rank=int.from_bytes(hashlib.blake2s(repr((seed,index)).encode(),digest_size=4).digest(),'little')
        accent=0 if abs(phase-round(phase))<.008 else 1 if abs(phase*2-round(phase*2))<.015 else 2
        candidates.append((accent,rank,index,beat,ms,k,r))
    ledger=[]
    for _,_,index,beat,ms,k,r in sorted(candidates):
        if len(ledger)>=wanted:break
        pos=bisect.bisect_left(times,ms)
        if (pos and ms-times[pos-1]<80) or (pos<len(times) and times[pos]-ms<80):continue
        lane=oldcols+int(round(beat*subdivisions))%4
        row=list(result['splits'][k]['rows'][r] or [0]*result['cols']);assert row[lane]==0;row[lane]=sources.TAP
        result['splits'][k]['rows'][r]=tuple(row);bisect.insort(times,ms)
        ledger.append(dict(kind='ADD_MUSICAL_SUBDIVISION',source_virtual_lane=lane,row=index,beat=beat,ms=ms,reason='Human-authorized density expansion on active musical phrase grid',source_normal_notes_changed=False))
    result=nx20.parse(nx20.build(result))
    if verify:audit_extension(source,result,ledger)
    return result,ledger,dict(original_onsets=len(events),added_onsets=len(ledger),requested_added_onsets=wanted,target_row_nps=target_row_nps,achieved_reference_row_nps=len(times)/duration,original_heads_holds_preserved=True,maximum_original_head_tail_error_ms=clock_error,internal_reference_only=True,installed=False)

def audit_extension(source,augmented,ledger):
    # Independent multiset comparison: virtual lanes can add attacks but must
    # never disguise removal, conversion or early release of an original hold.
    compare_original_clocks(source,augmented)
    def body_ticks(nx,limit):
        tl=sources.timeline(nx)
        return Counter((lane,round(ms,5)) for _,ms,k,r in tl for lane,v in enumerate(nx['splits'][k]['rows'][r] or ()) if lane<limit and (v&255)==0x5b)
    old=body_ticks(source,source['cols']);new=body_ticks(augmented,source['cols'])
    oldrows=sorted(old.elements());newrows=sorted(new.elements())
    if len(oldrows)!=len(newrows) or any(a[0]!=b[0] or abs(a[1]-b[1])>=.1 for a,b in zip(oldrows,newrows)):raise ValueError('Original scoring hold ticks changed')
    _,events=sources.events_of(augmented)
    actual=Counter((lane,round(e['ms'],5)) for e in events for lane in e['lanes'] if lane>=source['cols'])
    expected=Counter((entry['source_virtual_lane'],round(entry['ms'],5)) for entry in ledger)
    if actual!=expected:raise ValueError('Added note ledger does not match actual virtual-lane heads')
    if any(e['holds'] and any(lane>=source['cols'] for _,lane in e['holds']) for e in events):raise ValueError('Unexpected invented hold')
    return True
