import sys,json
sys.path[:0]=[r'D:\Pump It Up Data\PIU\final_generation_v362']
import playability as P
C=P.SINGLE;N=['DL','UL','C','UR','DR']
pats=json.load(open(r'D:\Pump It Up Data\PIU\final_generation_v362\vendor_v363\hybrid\user_patterns_single.json',encoding='utf8'))['patterns']
idx={n:i for i,n in enumerate(N)}
for p in pats:
    lanes=[idx[x] for x in p['panels']]
    best=None
    for first in (0,1):
        for l0 in range(5):
            for r0 in range(5):
                if l0==r0:continue
                pos=[l0,r0];f=first;rows=[];ok=True
                for ln in lanes:
                    if ln==pos[1-f]:ok=False;break
                    pos[f]=ln;y=P.yaw(C,pos[0],pos[1]);rows.append((N[ln],'LR'[f],round(y)));f=1-f
                if not ok:continue
                w=max(abs(r[2]) for r in rows);n=sum(abs(r[2])>90 for r in rows)
                key=(w,n)
                if best is None or key<best[0]:best=(key,first,N[l0],N[r0],rows)
    (w,n),first,l0,r0,rows=best
    print(p['id'],'start',('L' if first==0 else 'R'),'from L=%s R=%s'%(l0,r0),'max|yaw|',w,'steps>90:',n)
    print('   ',' '.join(f"{a}{b}{'*' if abs(c)>90 else ''}" for a,b,c in rows))
