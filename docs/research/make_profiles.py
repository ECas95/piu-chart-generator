"""Derive exact-level profiles without rereading native files."""
from pathlib import Path
from collections import defaultdict
import json
from audit_official import quant
ROOT=Path(__file__).resolve().parent
raw=json.loads((ROOT/'official_chart_metrics.json').read_text(encoding='utf8'))
winner={}
for r in raw['charts']:
    key=(r['song'],r['mode'],r['level'])
    helper=int(Path(r['path']).parent.name,16)!=r['song']
    score=(r['game']=='PH',helper)
    if key not in winner or score>=winner[key][0]:winner[key]=(score,r)
selected=[r for _,r in winner.values()]
exclude={'game','song','title','path','mode','level','branches','notes','rows'}
def measure(rr):
    fields=set().union(*(set(r) for r in rr))-exclude
    return {key:quant([r[key] for r in rr if key in r]) for key in sorted(fields)}
profiles={}
for cols,mode in [(5,0),(10,2)]:
    for level in range(1,29):
        rr=[r for r in selected if r['mode']==mode and r['level']==level]
        if rr:profiles[f'{cols}_{level}']={'charts':len(rr),'metrics':measure(rr)}
    for low,hi in [(1,5),(6,10),(11,15),(16,20),(21,28)]:
        rr=[r for r in selected if r['mode']==mode and low<=r['level']<=hi]
        if rr:profiles[f'{cols}_{low}-{hi}']={'charts':len(rr),'metrics':measure(rr)}
(ROOT/'official_profiles.json').write_text(json.dumps({'raw_charts':len(raw['charts']),'deduplicated_charts':len(selected),
    'selection':'Prefer PHOENIX then native helper revisions for each song/mode/level','profiles':profiles},indent=2),encoding='utf8')
raw['summary']=[{'columns':cols,'levels':[low,hi],'charts':profiles[f'{cols}_{low}-{hi}']['charts'],
    'metrics':profiles[f'{cols}_{low}-{hi}']['metrics']} for cols in (5,10) for low,hi in [(1,5),(6,10),(11,15),(16,20),(21,28)] if f'{cols}_{low}-{hi}' in profiles]
(ROOT/'official_chart_metrics.json').write_text(json.dumps(raw,indent=2),encoding='utf8')
print('raw',len(raw['charts']),'deduplicated',len(selected))
for key in ('5_3','5_5','5_8','5_10','10_3','10_5','10_8','10_10','10_15','10_20'):
    if key in profiles:
        p=profiles[key];m=p['metrics']
        print(key,'n',p['charts'],'row_NPS',m['row_nps']['p50'],'peak4 p75',m['peak_row_4s']['p75'],
              'jump p50/p90',m['jump_rows']['p50'],m['jump_rows']['p90'],'hold p90',m['hold_heads']['p90'])
