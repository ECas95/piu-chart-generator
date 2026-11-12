"""Writes into user_patterns_single.json, per pattern, its natural-reading turns at 150 BPM 8ths/16ths: 'turns' (steps
beyond 45 deg), 'crossovers' (90-135), 'max_cross_run', 'steps'. The algorithm budgets turns per level with these."""
import sys,json
sys.path[:0]=[r'D:\Pump It Up Data\PIU\final_generation_v362',r'D:\Pump It Up Data\PIU\final_generation_v362\user_patterns']
import playability
from check_rows import events as row_events
p=r'D:\Pump It Up Data\PIU\final_generation_v362\vendor_v363\hybrid\user_patterns_single.json'
d=json.load(open(p,encoding='utf8'));P={'DL':0,'UL':1,'C':2,'UR':3,'DR':4}
for u in d['patterns']:
    if 'panels' in u:ev=[dict(index=i,ms=1000+i*100.,beat=i/4,lanes=[P[x]],holds=[],hold_ends_ms={}) for i,x in enumerate(u['panels'])]
    else:ev=row_events(u['rows'],150,0)
    a=playability.assess(ev,5)
    path=playability.solve(ev,5)['path'];foot=lambda st:st[3][0][0] if len({f for f,_ in st[3]})==1 else None
    u['start_foot'],u['end_foot']=foot(path[0]),foot(path[-1])
    u['feet']=[(lambda f:2 if f is None else f)(foot(st)) for st in path]   # per step: 0 left, 1 right, 2 both
    order={round(e['ms']):i for i,e in enumerate(ev)};crossed=sorted(order[f[0]] for f in a['all_flags'] if f[1] in ('CROSS','LONG_CROSS'))
    run=best=0;prev=None
    for i in crossed:run=run+1 if prev is not None and i==prev+1 else 1;best=max(best,run);prev=i
    u['max_cross_run']=best
    kinds=[f[1] for f in a['all_flags']]
    u['steps']=len(ev);u['turns']=sum(k in ('TWIST90','CROSS','LONG_CROSS') for k in kinds);u['crossovers']=sum(k in ('CROSS','LONG_CROSS') for k in kinds)
    u['max_yaw']=a['worst_yaw']
    print(u['id'],'feet',u['start_foot'],u['end_foot'],'turns',u['turns'],'run',u['max_cross_run'])
json.dump(d,open(p,'w',encoding='utf8'),ensure_ascii=False,indent=1)
