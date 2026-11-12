"""Post-generation source-to-Pump skill execution audit (no learning claims).

Distinguishes a BMS rhythmic intent from what the physical foot plan
ACTUALLY expresses. Crossover/twist certification remains unavailable.
"""
from __future__ import annotations
from collections import Counter


def _single_source(e):
    return e['lanes'][0] if len(e['lanes'])==1 and not e.get('holds') else None


def observe(source_events, plan):
    actions={p['index']:p['actions'] for p in plan}
    source={e['index']:e for e in source_events}
    ordered=[source[idx] for idx in sorted(actions)]
    groups={'drill':{'source_windows':0,'realized':0,'examples_failed':[]},
            'run':{'source_windows':0,'realized':0,'examples_failed':[]},
            'chord':{'source_rows':0,'preserved_two_head_rows':0},
            'hold':{'source_rows':0,'output_holds':0}}
    for e in ordered:
        out=actions[e['index']]
        if len(e['lanes'])>=2:
            groups['chord']['source_rows']+=1
            if len(out)>=2:groups['chord']['preserved_two_head_rows']+=1
        if e.get('holds'):
            groups['hold']['source_rows']+=1
            groups['hold']['output_holds']+=sum(a[2]>=0 for a in out)
    for i in range(len(ordered)-3):
        block=ordered[i:i+4]
        keys=[_single_source(e) for e in block]
        if any(k is None for k in keys):continue
        gaps=[block[k+1]['beat']-block[k]['beat'] for k in range(3)]
        if not all(0<g<=0.8 for g in gaps):continue
        out=[actions[e['index']] for e in block]
        if any(len(a)!=1 for a in out):continue
        panels=[a[0][0] for a in out]
        feet=[a[0][1] for a in out]
        alternating=all(a!=b for a,b in zip(feet,feet[1:]))
        if keys[0]==keys[2] and keys[1]==keys[3] and keys[0]!=keys[1]:
            x=groups['drill'];x['source_windows']+=1
            realized=(panels[0]==panels[2] and panels[1]==panels[3]
                      and panels[0]!=panels[1] and alternating)
            x['realized']+=bool(realized)
            if not realized and len(x['examples_failed'])<16:
                x['examples_failed'].append({'beat':block[0]['beat'],
                    'input_keys':keys,'output_panels':panels,'feet':feet})
        elif all(g<=0.55 for g in gaps) and len(set(keys))>=3:
            x=groups['run'];x['source_windows']+=1
            realized=alternating and len(set(panels))>=3
            x['realized']+=bool(realized)
            if not realized and len(x['examples_failed'])<16:
                x['examples_failed'].append({'beat':block[0]['beat'],
                    'input_keys':keys,'output_panels':panels,'feet':feet})
    for skill in ('drill','run'):
        x=groups[skill];x['realized_fraction']=(x['realized']/x['source_windows']
                                               if x['source_windows'] else None)
    return {'measured':groups,
            'limitations':{'twist': 'not certified; no continuous torso orientation or heel/toe model',
                           'crossover': 'not certified; two-contact model and angle proxy only',
                           'footswitch': 'not certified without lift/release and setup-time foot model',
                           'bracket': 'not implemented; simultaneous heads cannot share one foot'},
            'meaning':'A/B source-key drill preservation and alternating-foot runs; not human playability'}
