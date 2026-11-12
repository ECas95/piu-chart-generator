"""Explicit human authorization: whole-hold simplification in new EASY variants only.

Keep the attack as a tap; remove the entire body and tail, never shorten a hold.
This returns a derived copy and an individual source-clock ledger, not an edit
to any original or installed chart. Selection must be explicit per hold.
"""
import copy
from collections import Counter
from collections import defaultdict
from hybrid import sources

AUTHORITY='Sí, simplificar sólo las variantes nuevas fáciles'

def density_hold_keys(source, *, band, target_density):
    """Keep rhythmically salient complete holds within each EASY phrase budget.

    Excess holds become taps, then ordinary EASY onset selection may reduce
    those taps with its own ledger. Never move or truncate a retained hold.
    """
    if band not in (1,2):raise ValueError('Density hold simplification is EASY-only')
    tl,events=sources.events_of(source);origin=tl[0][0];groups=defaultdict(list);keys=[]
    for e in events:groups[int((e['beat']-origin)//8)].append(e)
    for phrase,es in groups.items():
        holds=[(e,end,lane) for e in es for end,lane in e['holds']]
        span=max(.5,(es[-1]['ms']-es[0]['ms'])/1000)
        # v363: native hold-row share is ~1% at levels1-5 and ~7% at6-12; the
        # v362 budget (half of all onsets) gave 10-26% hold rows in EASY charts.
        budget=round(target_density*span*(.08 if band==1 else .07));kept=[]
        ordered=sorted(holds,key=lambda x:(abs((x[0]['beat']-origin)-round(x[0]['beat']-origin))>1e-5,x[0]['ms'],x[2]))
        for e,end,lane in ordered:
            if band==1 and abs((e['beat']-origin)-round(e['beat']-origin))>1e-5:
                keys.append((e['index'],lane));continue # Beginner offbeat hold -> tap; EASY selector separately ledgers onset reduction.
            if len(kept)<budget and all(abs(e['ms']-at)>=min(750.,650/max(target_density,.1)) for at in kept):kept.append(e['ms'])
            else:keys.append((e['index'],lane))
    return sorted(keys)

def concurrency_hold_keys(source):
    """v363: two feet hold at most two panels. Holds that would make a third
    simultaneous hold become taps in NEW variants only (ledgered per hold)."""
    _,events=sources.events_of(source);active=[];keys=[]
    for e in events:
        active=[end for end in active if end>e['ms']+.1]
        for end,lane in sorted(e['holds'],key=lambda h:h[1]):
            if len(active)>=2:keys.append((e['index'],lane))
            else:active.append(e['hold_ends_ms'][end])
    return keys

def simplify(source, keys, *, band, verify=True, structural=()):
    keys=set(tuple(k) for k in keys)
    if keys-set(map(tuple,structural)) and band not in (1,2):
        raise ValueError('Whole-hold simplification authorized only for new EASY bands 1 and 2')
    out=copy.deepcopy(source);tl,events=sources.events_of(source);ledger=[];found=set()
    for e in events:
        for end,lane in e['holds']:
            key=(e['index'],lane)
            if key not in keys:continue
            found.add(key);removed=[]
            for i in range(e['index'],end+1):
                _,ms,k,r=tl[i];row=list(out['splits'][k]['rows'][r] or (0,)*source['cols']);old=row[lane]
                if i>e['index'] and not old:continue   # cell already cleared by an overlapping source hold
                if i==e['index']:
                    assert old&255==0x57;row[lane]=sources.TAP
                else:
                    assert old&255==(0x5f if i==end else 0x5b)
                    removed.append(dict(index=i,ms=ms,cell=old));row[lane]=0
                out['splits'][k]['rows'][r]=tuple(row) if any(row) else None
            ledger.append(dict(kind='SIMPLIFY_WHOLE_HOLD_TO_TAP',source_index=e['index'],source_lane=lane,start_ms=e['ms'],end_ms=tl[end][1],removed_cells=removed,band=band,authority=AUTHORITY,original_preserved=True))
    if found!=keys:raise ValueError('Requested hold key not found in original reference')
    if not verify:return out,ledger
    # Independently compare every cell: only the selected complete intervals differ.
    allowed={(x['source_index'],x['source_lane']):sources.TAP for x in ledger}
    for x in ledger:
        allowed.update({(c['index'],x['source_lane']):0 for c in x['removed_cells']})
    for i,(_,_,k,r) in enumerate(tl):
        a=source['splits'][k]['rows'][r] or (0,)*source['cols']
        b=out['splits'][k]['rows'][r] or (0,)*source['cols']
        for lane,(old,new) in enumerate(zip(a,b)):
            assert new==allowed.get((i,lane),old),'Unledgered source cell change'
    _,after=sources.events_of(out)
    assert Counter((e['ms'],lane) for e in events for lane in e['lanes'])==Counter((e['ms'],lane) for e in after for lane in e['lanes'])
    return out,ledger
