"""Self-check v3.1: on a plain 16th stream (level 18) the composer follows most chained user patterns note for note
(panel and foot) and the result passes the gate (every crossover sits inside a followed pattern, see compose)."""
import sys
sys.path[:0]=[r'D:\Pump It Up Data\PIU\final_generation_v362',r'D:\Pump It Up Data\PIU\final_generation_v362\vendor_v363']
from hybrid import composer
import playability
ev=[dict(index=i,beat=i/4,ms=1000+i*100.,lanes=[(i*3)%5],holds=[],hold_ends_ms={},hold_ends_beat={}) for i in range(128)]
r=composer.compose(ev,5,18,'HARD',32,7,6.8,pose_policy='soft',recovery_policy='strict')
pos={p['index']:p for p in r['plan']}
followed=sum(sorted(a[0] for a in pos[ix]['actions'])==sorted(h if isinstance(h,tuple) else (h,)) and (r['user_feet'].get(ix,2)==2 or [a[1] for a in pos[ix]['actions']]==[r['user_feet'][ix]]) for ix,h in r['user_hints'].items())
print('user notes',len(r['user_hints']),'followed',followed,'segments',[len(s) for s in r['user_segments']])
assert followed>=.7*len(r['user_hints'])>0
out=[dict(index=p['index'],ms=1000+p['index']*100.,lanes=[a[0] for a in p['actions']],holds=[],hold_ends_ms={}) for p in r['plan']]
g=playability.gate(out,5,4);print('gate',g['pass'],'cross',g['crossovers'],'back',g['back_facing'])
assert g['pass']
print('CHAIN_OK')
