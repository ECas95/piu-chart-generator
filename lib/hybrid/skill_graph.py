"""Source-first Pump Single skill annotations.

This is a structural *intent* detector, not a claim about executed footwork.
No source heads, beats or hold endpoints are changed here.
"""
from __future__ import annotations
from collections import Counter


def _key(event):
    lanes=event.get('lanes', ())
    return lanes[0] if len(lanes)==1 and not event.get('holds') else None


def annotate(events):
    """Annotate each original onset; grouped rhythmic skills take precedence.

    DRILL  A-B-A-B or B-A-B-A across 4 consecutive single-head attacks.
    RUN    >=4 successive single-head events with consecutive gaps <=0.55 beat
           and at least 3 distinct input keys; not necessarily a PIU run until executed.
    REPEAT  >=3 original same-key attacks; footswitch *opportunity*, not implementation.
    CHORD/HOLD always reflect the source attack's cardinality/hold headers.
    """
    tags={e['index']:'FLOW' for e in events}
    for i,e in enumerate(events):
        if e.get('holds'):tags[e['index']]='HOLD'
        elif len(e['lanes'])>1:tags[e['index']]='CHORD'
    for i in range(len(events)-3):
        chunk=events[i:i+4]
        keys=[_key(e) for e in chunk]
        gaps=[chunk[k+1]['beat']-chunk[k]['beat'] for k in range(3)]
        if any(k is None for k in keys) or not all(0<g<=0.8 for g in gaps):continue
        if keys[0]==keys[2] and keys[1]==keys[3] and keys[0]!=keys[1]:
            for e in chunk:tags[e['index']]='DRILL'
        elif len(set(keys))>=3 and all(g<=0.55 for g in gaps):
            for e in chunk:
                if tags[e['index']]=='FLOW':tags[e['index']]='RUN'
    for i in range(2,len(events)):
        a,b,c=events[i-2:i+1]
        if all(_key(e) is not None for e in (a,b,c)) and _key(a)==_key(b)==_key(c):
            if 0<c['beat']-a['beat']<=4:
                for e in (a,b,c):
                    if tags[e['index']]=='FLOW':tags[e['index']]='REPEAT'
    return tags


def skill_report(events, tags):
    counts=Counter(tags.values())
    byphrase={}
    for e in events:
        q=int(e['beat']//8)*8
        d=byphrase.setdefault(q,Counter());d[tags[e['index']]]+=1
    return {'source_derived_skills':dict(counts),
            'phrases':[{'start_beat':q,'intent':max(c,key=lambda x:(c[x],x)),
                        'counts':dict(c)} for q,c in sorted(byphrase.items())],
            'limitations':['labels describe input-key motifs, not guaranteed Pump skills',
                           'footswitch, true crossover/twist, brackets and spin are not certified by this detector']}
