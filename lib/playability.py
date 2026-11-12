"""Natural-play foot solver: how a human would read a chart, independent of the generator plan.

Viterbi over (left_panel, right_panel, last_foot). A player alternates feet,
avoids crossing and never wants to face backwards; the cheapest path is the
"natural" reading. If even that path must face backwards or double-step fast,
the chart is unplayable as written. Used as a hard gate after generation.
"""
from __future__ import annotations
import math, sys, json
from itertools import permutations, combinations

SINGLE=((-1.,-1.),(-1.,1.),(0.,0.),(1.,1.),(1.,-1.))
DOUBLE=tuple((x-1.5,y) for x,y in SINGLE)+tuple((x+1.5,y) for x,y in SINGLE)
CE_PANELS={2,7}


def yaw(coords,l,r):
    (lx,ly),(rx,ry)=coords[l],coords[r]
    return math.degrees(math.atan2(-(ry-ly),rx-lx))


def bracketable(coords,a,b):
    # one foot on two panels: heel/toe CE+corner (adjacent, distance sqrt2)
    return abs(math.dist(coords[a],coords[b])-2**.5)<1e-6 and (a in CE_PANELS or b in CE_PANELS)


def _stance_cost(coords,l,r):
    if l==r:return 0.                  # footswitch overlap, transient
    y=abs(yaw(coords,l,r))
    if y>135+1e-6:return 400.          # fully back-facing
    if y>90+1e-6:return 25.            # twist beyond 90
    if y>45+1e-6:return 3.             # 90-degree twist / side-facing
    return 0.


def _options(lanes,free,coords):
    n=len(lanes)
    if n==1:return [((f,lanes[0]),) for f in free]
    if n==2:
        out=[((a,lanes[0]),(b,lanes[1])) for a,b in permutations(free,2)]
        if bracketable(coords,*lanes):out+=[((f,lanes[0]),(f,lanes[1])) for f in free]
        return out
    out=[]
    for a,b in permutations(free,2):
        for i in range(n):
            rest=[x for k,x in enumerate(lanes) if k!=i]
            if len(rest)==2 and bracketable(coords,*rest):out.append(((a,lanes[i]),(b,rest[0]),(b,rest[1])))
    if n==4 and len(free)==2:
        for x in combinations(lanes,2):
            y=[l for l in lanes if l not in x]
            if bracketable(coords,*x) and bracketable(coords,*y):
                out.append(((0,x[0]),(0,x[1]),(1,y[0]),(1,y[1])))
    return out


def solve(events,columns):
    """events: [{'ms','lanes','holds':[(end_index,lane)],'hold_ends_ms':{end:ms}}]. Returns cheapest natural path."""
    coords=SINGLE if columns==5 else DOUBLE
    start=(0,4) if columns==5 else (3,6)
    # key (pos,last,hold) -> (cost, foot_times, backpointer)
    frontier={(start,-1,(-1.,-1.)):(0.,(-1e9,-1e9),None)}
    for e in events:
        now=e['ms'];lanes=list(e['lanes'])
        holdlanes={lane:e['hold_ends_ms'][end] for end,lane in e['holds']}
        nxt={}
        for (pos,last,hold),(cost,ftimes,bp) in frontier.items():
            hold=tuple(h if h>now+1e-6 else -1. for h in hold)
            free=[f for f in (0,1) if hold[f]<0]
            for acts in _options(lanes,free,coords):
                p=list(pos);t=list(ftimes);h=list(hold);c=0.
                feet=[f for f,_ in acts]
                single=len(acts)==1
                for f in set(feet):
                    mine=[lane for g,lane in acts if g==f]
                    # bracket: foot lands on the corner, heel/toe covers CE
                    lane=mine[0] if len(mine)==1 else [l for l in mine if l not in CE_PANELS][0]
                    dt=max(now-t[f],1.)
                    if lane==p[f]:
                        c+=.3 if dt>=140 else 4.             # jack
                    elif lane==p[1-f] and h[1-f]<0 and single:
                        c+=1.5                               # footswitch: other foot lifts
                    elif lane==p[1-f]:
                        c=None;break
                    else:
                        d=math.dist(coords[p[f]],coords[lane]);c+=d*d*250./dt
                    if len(mine)==2:c+=2.
                    p[f]=lane;t[f]=now
                if c is None:continue
                for f,lane in acts:
                    if lane in holdlanes:h[f]=max(h[f],holdlanes[lane])
                if not single and p[0]==p[1]:continue
                c+=_stance_cost(coords,p[0],p[1])
                if single:
                    f=feet[0]
                    if f==last and h[1-f]<0 and lanes[0]!=pos[f]:
                        gap=now-ftimes[f]
                        c+=150. if gap<200 else 40. if gap<300 else 8. if gap<500 else 1.
                    nl=f
                else:nl=-1
                key=(tuple(p),nl,tuple(h));total=cost+c
                if key not in nxt or total<nxt[key][0]:
                    nxt[key]=(total,tuple(t),(bp,(tuple(p),nl,now,acts,pos,single and hold[1-feet[0]]>=0)))
        if not nxt:return {'ok':False,'reason':'NO_TWO_FOOT_READING','ms':now}
        frontier=nxt
    best=min(frontier.values(),key=lambda v:v[0])
    path=[];bp=best[2]
    while bp:bp,step=bp;path.append(step)
    path.reverse()
    return {'ok':True,'cost':best[0],'path':path}


MAX_CROSS_STEPS=4   # user-validated patterns (2026-10-31) hold a crossover for up to 4 steps and then return
MAX_CROSS_STEPS_LOW=2   # v3: official level 6-12 charts keep crossovers to 1-2 steps


def assess(events,columns,max_cross=MAX_CROSS_STEPS):
    """Natural reading metrics. back = stance beyond 135 deg (de espaldas); cross = 90..135 deg, a crossover the
    player holds briefly with the torso front (user-validated patterns), unplayable only past max_cross steps."""
    MAX_CROSS_STEPS=max_cross
    r=solve(events,columns)
    if not r['ok']:return dict(playable=False,rows=len(events),worst_yaw=999.,**r)
    coords=SINGLE if columns==5 else DOUBLE
    back=twist=cross=long_cross=fastdouble=0;flags=[];worst=0.;prev=None;crossed=0
    for pos,last,ms,acts,before,held in r['path']:
        y=abs(yaw(coords,*pos)) if pos[0]!=pos[1] else 0.
        worst=max(worst,y)
        crossed=crossed+1 if 90+1e-6<y<=135+1e-6 else 0
        if y>135+1e-6:back+=1;flags.append((round(ms),'BACK',pos))
        elif crossed>MAX_CROSS_STEPS:long_cross+=1;flags.append((round(ms),'LONG_CROSS',pos))
        elif crossed:cross+=1;flags.append((round(ms),'CROSS',pos))
        elif y>45+1e-6:twist+=1;flags.append((round(ms),'TWIST90',pos))
        if prev and last>=0 and not held and prev[0]==last and pos[last]!=before[last] and ms-prev[1]<200:
            fastdouble+=1;flags.append((round(ms),'FAST_DOUBLESTEP',pos))
        prev=(last,ms) if last>=0 else None
    return dict(playable=back==0 and long_cross==0 and fastdouble==0,rows=len(r['path']),back_facing=back,twists=twist,
                crossovers=cross,long_crossovers=long_cross,
                fast_doublesteps=fastdouble,worst_yaw=round(worst,1),cost=round(r['cost'],1),first_flags=flags[:8],
                all_flags=flags)


def gate(events,columns,band):
    """Hard gate for generated charts: never backwards. v3, as official FIESTA 2 / PRIME / XX charts: band 1 (1-5)
    stays front-facing (45 deg); band 2 (6-12) allows twists and crossovers of 1-2 steps; bands 3-4 (13+) up to 4."""
    m=assess(events,columns,MAX_CROSS_STEPS_LOW if band==2 else MAX_CROSS_STEPS)
    m['pass']=bool(m['playable'] and m['worst_yaw']<=(135. if band>=2 else 45.)+1e-6)
    # spots to omit on failure: backwards, long crossovers and fast double steps always; twists/crossovers in band 1
    m['problem_ms']=[f[0] for f in m.pop('all_flags',[]) if f[1] not in ('TWIST90','CROSS') or band<2]
    return m


def assess_nx(path):
    from pathlib import Path
    here=Path(__file__).resolve().parent
    sys.path[:0]=[str(here)]
    from hybrid import nx20,sources
    nx=nx20.parse(Path(path).read_bytes());_,ev=sources.events_of(nx)
    return assess(ev,10 if nx['cols']==10 else 5)


def _selftest():
    ev=lambda ms,*l:{'ms':ms,'lanes':list(l),'holds':[],'hold_ends_ms':{}}
    # front-facing alternating stream
    ok=assess([ev(i*150,l) for i,l in enumerate([1,3,1,3,0,4,0,4,2,4,2,4])],5)
    assert ok['playable'],ok
    # forced spin: fast run around the pad in one direction twice -> must twist past 90
    bad=assess([ev(i*110,l) for i,l in enumerate([1,3,4,0,1,3,4,0,1,3,4,0])],5)
    assert not bad['playable'],bad
    # user-validated crossover run (pattern U8, 16ths at 150 BPM) is playable in band 4, not in band 2
    u8=[ev(i*100,l) for i,l in enumerate([0,3,2,1,4,1,2,3,0,2,1,3,1,2,0,4,2])]
    assert gate(u8,5,4)['pass'] and not gate(u8,5,2)['pass'],assess(u8,5)
    print('selftest ok',ok['worst_yaw'],bad['back_facing'],bad['twists'],bad['fast_doublesteps'])


if __name__=='__main__':
    if len(sys.argv)==1:_selftest()
    else:
        for p in sys.argv[1:]:print(p,json.dumps(assess_nx(p)))
