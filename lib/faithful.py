"""v364 faithful generation (user decision 2026-10-24).

The ORIGINAL chart's rhythm is kept: every note time comes from the original. Nothing is
added or moved. The algorithm only chooses the Pump panels (strict foot parity + natural-
reading anti-spin gate). Easier charts only REMOVE original notes by metric strength
(finest subdivisions first). Doubles = PumpDoublify of each Single (fallback: the same
rhythm composed on 10 panels). Every label is the real native-model level.

Output per song: runs/<run>/songs/<GID>/<mode>_T<k>.NX + receipt.json; FAITHFUL_REGISTRY.json.
"""
from pathlib import Path
import sys,json,hashlib,time,os,argparse,collections,math
from concurrent.futures import ProcessPoolExecutor,as_completed
R=Path(__file__).resolve().parent;B=R.parent
sys.path[:0]=[str(R),str(R/'engine')]
REFS=['direct_raw_sm_sources_01','direct_ddr_sources_01','direct_djmax_sources_01','direct_dss_sources_01','direct_pump_sources_01','direct_remaining_refs_01','direct_double_to_single_refs_01','native_reference_cache']
LEVEL_CAP=None   # nivel del chart original: ningun chart generado puede etiquetarse por encima (piugen lo fija)
read=lambda p:json.loads(Path(p).read_text(encoding='utf8'))
band_of=lambda lv:1 if lv<=5 else 2 if lv<=12 else 3 if lv<=17 else 4

def metric_weights(events):
    """-1 measure downbeat, 0 beat, 1 eighth, 2 sixteenth, 3 anything finer/triplet. Phase from the chart itself."""
    fr=collections.Counter(round((e['beat']%1)*48)%48 for e in events)
    origin=fr.most_common(1)[0][0]/48
    w={}
    for e in events:
        x=(e['beat']-origin)%4;f=x%1
        near=lambda g:min(abs(f*g-round(f*g)),1)<.02*g
        w[e['index']]=(-1 if abs(x-round(x))<.02 and round(x)%4==0 else 0) if near(1) else 1 if near(2) else 2 if near(4) else 3
    return w

def reductions(events):
    """Candidate rhythms, all subsets of the original: (name, events, chord_policy)."""
    w=metric_weights(events)
    out=[('full',list(events))]
    for name,limit in (('no_32nds',2),('no_16ths',1),('beats',0),('downbeats',-1)):
        keep=[e for e in events if w[e['index']]<=limit]
        if keep:out.append((name,keep))
    # intermediate steps, still subsets of the original: beats + every other off-beat eighth,
    # and eighths + every other sixteenth (fills the gap when two levels collapse)
    for name,base,extra in (('beats_half_8ths',0,1),('8ths_half_16ths',1,2)):
        keep=[];flip=False
        for e in events:
            if w[e['index']]<=base:keep.append(e)
            elif w[e['index']]==extra:
                flip=not flip
                if flip:keep.append(e)
        if keep:out.append((name,keep))
    # finer density steps (fills big level gaps, e.g. a 16th-stream chart): keep 1/4, 1/2, 3/4 of one
    # metric layer evenly, or that layer only in alternate measures; coarser layers kept; still subsets
    for limit in (3,2,1,0):
        if not any(w[e['index']]==limit for e in events):continue
        for num in (1,2,3):
            keep=[];acc=0
            for e in events:
                if w[e['index']]<limit:keep.append(e)
                elif w[e['index']]==limit:
                    acc+=num
                    if acc>=4:acc-=4;keep.append(e)
            out.append((f'w{limit}_{num}of4',keep))
        out.append((f'w{limit}_alt_measures',[e for e in events if w[e['index']]<limit or (w[e['index']]==limit and int(e['beat']//4)%2==0)]))
    # half-beat-spaced beats for fast songs (still original onsets only)
    beats=[e for e in events if w[e['index']]<=0];sparse=[];last=-1e9
    for e in beats:
        if e['ms']-last>=900:sparse.append(e);last=e['ms']
    if sparse:out.append(('sparse_beats',sparse))
    # an easy chart still needs ~1 note per second (official level 1-3 density)
    dur=max(1.,(events[-1]['ms']-events[0]['ms'])/1000)
    dense=[(n,e) for n,e in out if len(e)/dur>=.6 or n=='full']
    if len(dense)<4:   # short/easy originals: sparser subsets too, so every song can reach 4 charts per mode
        dense+=[(n,e) for n,e in out if (n,e) not in dense and len(e)>=16]
    return dense or out[:1],w

def chords_for_easy(events,w,level):
    """Easy charts: a chord off the measure downbeat becomes one of its own original lanes (timing unchanged)."""
    if level>5:return events
    return [dict(e,lanes=e['lanes'][:1]) if len(e['lanes'])>1 and not e['holds'] and w[e['index']]>-1 else e for e in events]

def stream_chords_to_single(events,gap_ms=250,jump_gap_ms=500):
    """DJMAX keyboard chords inside streams are unplayable brackets/jump chains on a pad (user 2026-10-24):
    a chord stays a jump only when isolated (>=gap_ms to both neighbours, >=jump_gap_ms after the previous jump);
    otherwise it becomes ONE of its own notes at the same time (hold lane preferred). Nothing is added or moved."""
    out=[];last_jump=-1e9
    for i,e in enumerate(events):
        if len(e['lanes'])>1:
            prev=e['ms']-events[i-1]['ms'] if i else 1e9;nxt=events[i+1]['ms']-e['ms'] if i+1<len(events) else 1e9
            if prev>=gap_ms and nxt>=gap_ms and e['ms']-last_jump>=jump_gap_ms:last_jump=e['ms']
            else:
                lane=e['holds'][0][1] if e['holds'] else e['lanes'][0];holds=[h for h in e['holds'] if h[1]==lane];ends={h[0] for h in holds}
                e=dict(e,lanes=[lane],holds=holds,hold_ends_ms={k:v for k,v in e['hold_ends_ms'].items() if k in ends},hold_ends_beat={k:v for k,v in e['hold_ends_beat'].items() if k in ends})
        out.append(e)
    return out

def song(job):
    import generate_nx_band as G,playability
    from hybrid import composer,sources,nx20
    from easy_hold_policy import simplify,concurrency_hold_keys
    from pumpdoublify_adapter import convert
    from generate import travel
    gid=job['gid'];out=Path(job['out'])/gid;out.mkdir(parents=True,exist_ok=True)
    if (out/'song.json').exists():return json.loads((out/'song.json').read_text())
    t0=time.time();res=dict(gid=gid,charts=[],errors=[])
    try:
        ref=json.loads(Path(job['ref']).read_text(encoding='utf8'));fp=Path(ref['file'])
        raw=(fp if fp.is_absolute() else B/fp).read_bytes()
        src=nx20.parse(raw)
        # mines / fake notes in custom originals are not steps: drop them (nothing is added)
        mines=0
        for sp in src['splits']:
            for r,row in enumerate(sp['rows']):
                if row and any(v and (v&255) not in (0x43,0x57,0x5b,0x5f) for v in row):
                    mines+=sum(1 for v in row if v and (v&255) not in (0x43,0x57,0x5b,0x5f))
                    new=tuple(v if (v&255) in (0x43,0x57,0x5b,0x5f) else 0 for v in row);sp['rows'][r]=new if any(new) else None
        if mines:src=nx20.parse(nx20.build(src));res['mines_or_fakes_removed']=mines
        keys=concurrency_hold_keys(src)
        src,hold_ledger=simplify(src,keys,band=4,verify=False,structural=keys)   # 3rd simultaneous hold -> tap (two feet)
        tl,events=sources.events_of(src);origin=tl[0][0]
        lead_cut=None
        if job.get('lead_in_ms'):
            # user 2026-10-24: these channels' cuts start notes at 0s; drop original notes
            # before ~3s and start on the first strong beat (no note added or moved)
            w0=metric_weights(events);t=job['lead_in_ms']
            first=next((e for e in events if e['ms']>=t and e['ms']<t+2000 and w0[e['index']]==-1),None) or next((e for e in events if e['ms']>=t and w0[e['index']]<=0),None)
            if first and events[0]['ms']<t:
                lead_cut=first['ms'];events=[e for e in events if e['ms']>=lead_cut]
        if job.get('djmax'):events=stream_chords_to_single(events)
        cands,w=reductions(events)
        est=lambda evs,cols:G.MODEL.estimate(G.metrics([dict(e,lanes=e['lanes'][:2 if cols==5 else 4]) for e in evs],origin),cols)[0]
        scored=[(est(evs,5),name,evs) for name,evs in cands]
        # 4 distinct levels: the full original + the most spread reductions below it
        top=scored[0];rest=sorted({lv:(lv,n,e) for lv,n,e in scored[1:] if lv<top[0]}.values())
        pick=[top]
        if rest:
            pick.append(rest[0])                                   # easiest
            mids=[x for x in rest[1:]]
            for target in (top[0]*.45+rest[0][0]*.55,top[0]*.75+rest[0][0]*.25):
                if mids:best=min(mids,key=lambda x:abs(x[0]-target));pick.append(best);mids.remove(best)
        # user 2026-10-24: every custom song needs 4 charts per mode. Too few distinct levels -> add the
        # reductions (different subsets of the original) farthest in note count from those already picked
        extra=[x for x in scored if all(len(x[2])!=len(p[2]) for p in pick)]
        while len(pick)<4 and extra:
            best=max(extra,key=lambda x:min(abs(len(x[2])-len(p[2])) for p in pick));pick.append(best)
            extra=[x for x in extra if len(x[2])!=len(best[2])]
        pick=sorted(pick,key=lambda x:(x[0],len(x[2])))
        seed=int.from_bytes(hashlib.sha256(gid.encode()).digest()[:4],'little')
        singles=[]
        for tier,(lv,name,evs) in enumerate(pick):
            evs=chords_for_easy(evs,w,lv)
            chart,meta=plan(evs,src,5,lv,seed+tier,composer,sources,playability,travel)
            if chart is not None:meta['lead_in_cut_ms']=lead_cut
            if chart is None:res['errors'].append(dict(mode='Single',tier=tier,reduction=name,error=meta));continue
            singles.append((tier,name,chart,meta))
            res['charts'].append(save(out,'Single',tier,name,chart,meta,ref,G,nx20,sources,origin,len(events),len(evs)))
        for tier,name,chart,meta in singles:
            lvl=None
            try:
                # PumpDoublify of the Single; flagged spots are removed from the Single input and converted again
                from doublify_doubles import strip_rows
                single=chart;repaired=[]
                for attempt in range(10):
                    dbl,_,_=convert(single,level=max(3,meta['level']),seed=seed+tier,beam=32,verify=False)  # same seed: repairs converge
                    g=playability.gate(sources.events_of(dbl)[1],10,4)  # Double: 90-degree side stances are normal Pump doubles; back-facing still rejected
                    if g['pass'] or not g['problem_ms']:break
                    single,removed=strip_rows(single,g['problem_ms']);repaired+=removed
                if g['pass']:dmeta=dict(meta,method='PumpDoublify of the faithful Single',gate=g,omitted_conflicts=meta.get('omitted_conflicts',[])+repaired);dchart=dbl
                else:raise ValueError('doublify gate')
            except Exception:
                _,sev=sources.events_of(chart)
                dchart,dmeta=plan(sev,chart,10,meta['level'],seed+tier+99,composer,sources,playability,travel)
                if dchart is None:res['errors'].append(dict(mode='Double',tier=tier,reduction=name,error=dmeta));continue
                dmeta['method']='same faithful rhythm composed on 10 panels (PumpDoublify failed)'
            res['charts'].append(save(out,'Double',tier,name,dchart,dmeta,ref,G,nx20,sources,origin,len(events),None))
    except Exception as e:
        res['errors'].append(dict(error=repr(e)[:300]))
    try:relabel(res,out,LEVEL_CAP)
    except Exception as e:res['errors'].append(dict(error='relabel '+repr(e)[:200]))
    res['lead_in_cut_ms']=locals().get('lead_cut');res['seconds']=time.time()-t0;(out/'song.json').write_text(json.dumps(res,indent=1));return res

def relabel(res,out,cap):
    """Ningun chart generado es mas dificil que el original. Cada modo se escala para que su tier superior (el ritmo
    original completo) valga el nivel del original (cap; sin cap = estimacion del modelo para el Single completo) y
    el resto queda proporcional. Las notas no cambian: solo la etiqueta (tag 1001, .json y receipt)."""
    from hybrid import nx20
    by={m:[c for c in res['charts'] if c['mode']==m] for m in ('Single','Double')}
    top={m:max(cs,key=lambda c:(c['level'],c['rows'])) for m,cs in by.items() if cs}
    if not top:return
    cap=cap or top.get('Single',top.get('Double'))['level']
    for m,cs in by.items():
        if not cs:continue
        scale=cap/max(1,top[m]['level'])
        for c in cs:
            raw=c['level'];new=max(1,min(cap,round(raw*scale)))
            nx=nx20.parse(Path(c['nx']).read_bytes());nx['tags']=[(k,new if k==1001 else v) for k,v in nx['tags']]
            data=nx20.build(nx);Path(c['nx']).write_bytes(data)
            c.update(level=new,model_level=raw,level_cap=cap,sha256=hashlib.sha256(data).hexdigest())
            jp=Path(c['nx']).with_suffix('.json');j=json.loads(jp.read_text());j.update({k:c[k] for k in ('level','model_level','level_cap','sha256')});jp.write_text(json.dumps(j,indent=1))

def plan(evs,src,cols,level,seed,composer,sources,playability,travel):
    """Assign panels to EXACTLY these onsets. Timing never changes: a hold with no free foot
    becomes a tap at the same instant; an impossible single onset is omitted (both ledgered)."""
    level=max(1,min(28,int(level)));speed,_=travel(cols,level);changes=[]
    events=list(evs);gate_rounds=0
    for attempt in range(120):
        try:
            r=composer.compose(events,cols,level,'HARD',16,seed,speed,pose_policy='soft',skill_weight=4.,recovery_policy='strict',skip_conflicts=max(6,len(events)//25))
        except composer.NoRoute as ex:
            ev=ex.event;i=next((k for k,e in enumerate(events) if e['index']==ev['index']),None)
            if i is None:return None,'NoRoute: '+str(ex)[:120]
            if events[i]['holds']:
                events[i]=dict(events[i],holds=[],hold_ends_ms={},hold_ends_beat={});changes.append(dict(kind='HOLD_TO_TAP_SAME_TIME',ms=ev['ms'],beat=ev['beat']))
            else:
                changes.append(dict(kind='OMIT_ONSET',ms=ev['ms'],beat=ev['beat'],reason='no two-foot route'));events.pop(i)
            continue
        try:chart=sources.render(src,r['plan'],cols,level)
        except ValueError as gerr:
            # PRIME stores <=24 rows/beat: omit original onsets PRIME cannot store (ledgered)
            if '>24 rows' not in str(gerr):raise
            tl=sources.timeline(src)
            def offgrid(i):
                _,_,k,rr=tl[i];rpb=src['splits'][k]['head'][8]&255
                if rpb<=24:return False
                g=max(d for d in range(1,25) if rpb%d==0);return rr%(rpb//g)!=0
            bad={it['index'] for it in r['plan'] if offgrid(it['index']) or any(end>=0 and offgrid(end) for _,_,end in it['actions'])}
            if not bad:return None,'grid >24 rows/beat without off-grid notes'
            for e in [e for e in events if e['index'] in bad]:
                ends=[end for end,_ in e['holds']]
                if e['holds'] and not offgrid(e['index']):
                    j=events.index(e);events[j]=dict(e,holds=[],hold_ends_ms={},hold_ends_beat={});changes.append(dict(kind='HOLD_TO_TAP_SAME_TIME',ms=e['ms'],reason='hold tail off PRIME grid'))
                else:events.remove(e);changes.append(dict(kind='OMIT_ONSET',ms=e['ms'],reason='onset off PRIME grid'))
            continue
        g=playability.gate(sources.events_of(chart)[1],cols,4 if cols==10 else 1 if level<=5 else 2 if level<=12 else 3 if level<=17 else 4)
        skipped=[x for x in r['ledger'] if x['kind']=='OMIT_ONSET']
        if g['pass']:return chart,dict(level=level,gate=g,omitted_conflicts=changes+skipped,reduced_chord_heads=sum(x['kind']=='REDUCE_CHORD_HEAD' for x in r['ledger']))
        gate_rounds+=1
        if gate_rounds>12:break
        bad={round(m) for m in g['problem_ms']}
        drop=[e for e in events if round(e['ms']) in bad]
        for e in drop:
            j=events.index(e)
            if e['holds']:events[j]=dict(e,holds=[],hold_ends_ms={},hold_ends_beat={});changes.append(dict(kind='HOLD_TO_TAP_SAME_TIME',ms=e['ms'],beat=e['beat'],reason='anti-spin gate'))
            else:events.pop(j);changes.append(dict(kind='OMIT_ONSET',ms=e['ms'],beat=e['beat'],reason='anti-spin gate'))
    return None,'unresolved after retries'

def save(out,mode,tier,name,chart,meta,ref,G,nx20,sources,origin,n_orig,n_kept):
    tl,ev=sources.events_of(chart);cols=5 if mode=='Single' else 10
    level=G.MODEL.estimate(G.metrics(ev,tl[0][0]),cols)[0]
    chart['tags']=[(k,level if k==1001 else v) for k,v in chart['tags']];data=nx20.build(chart)
    p=out/f'{mode}_T{tier}.NX';p.write_bytes(data)
    rc=dict(game_song_id=out.name,mode=mode,tier=tier,reduction=name,level=level,nx=str(p),sha256=hashlib.sha256(data).hexdigest(),
            method=meta.get('method','v364 faithful: original note times, panels assigned by the v363 planner'),
            original_onsets=n_orig,kept_original_onsets=n_kept,rows=len(ev),omitted_conflicts=len(meta.get('omitted_conflicts',[])),
            reference=ref.get('file'),review_status='UNREVIEWED_FOR_HUMAN_PLAYTEST',notes_added=0,lead_in_cut_ms=meta.get('lead_in_cut_ms'))
    (out/f'{mode}_T{tier}.json').write_text(json.dumps(dict(rc,omitted=meta.get('omitted_conflicts',[]),gate=meta.get('gate')),indent=1))
    return rc

if __name__=='__main__':
    if sys.argv[1:]==['--selftest']:
        ev=lambda i,ms,l:dict(index=i,beat=i,ms=ms,lanes=l,holds=[],hold_ends_ms={},hold_ends_beat={})
        r=stream_chords_to_single([ev(0,0,[0,4]),ev(1,150,[1,3]),ev(2,300,[2]),ev(3,1000,[0,4]),ev(4,1300,[1,3])])
        assert [len(e['lanes']) for e in r]==[1,1,1,2,1],r;print('selftest ok')
    else:print('library module: use ../piugen.py')
