"""Self-check: a source with W4's exact shape (8th taps + 1-row holds ending on the next tap) gets W4 hints, and the
composer follows them (holds on the hinted panels)."""
import sys
sys.path[:0]=[r'D:\Pump It Up Data\PIU\final_generation_v362',r'D:\Pump It Up Data\PIU\final_generation_v362\vendor_v363']
from hybrid import musical,composer
ms=lambda r:1000+r*200.   # 150 BPM 8ths
ev=[]
for r in range(9):
    holds=[(r+1,0)] if r in (0,2,4,6) else []
    ev.append(dict(index=r,beat=r/2,ms=ms(r),lanes=[0],holds=holds,hold_ends_ms={e:ms(e) for e,_ in holds},hold_ends_beat={e:e/2 for e,_ in holds}))
musical._USER=None
h,log,_,_=musical.row_hints(ev,15,1)
print('patterns',log,'hints',h);assert log and log[0].rstrip('m') in ('W4','W11'),log
r=composer.compose(ev,5,15,'HARD',32,1,6.5,pose_policy='soft',recovery_policy='strict',user_patterns=(frozenset(),frozenset()))
got={p['index']:[a[0] for a in p['actions']] for p in r['plan']}
print('plan',got)
assert sum(sorted(got[i])==sorted(h[i]) for i in h)>=len(h)-1,'composer did not follow the row pattern'
print('ROW_HINTS_OK')
