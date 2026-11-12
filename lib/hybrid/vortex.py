"""ArrowVortex stream generator (src/Editor/StreamGenerator.cpp), ported for Pump Single and used as a panel source.

ArrowVortex fills a selected region at one spacing (4th .. 192nd) with a two-foot random walk that is always playable:
feet strictly alternate, the left foot never goes right of the right foot (pad x), a foot moves at most 2.2 panel units
(never DL<->UR), never onto the other foot's panel. The Difficulty slider sets the step length it aims for (0 small
moves around the centre, .5 uniform, 1 the widest moves).
Here the times never change (the original's notes): each section between rests gets the difficulty of its own
spacing, and every single tap no stronger source holds gets a random draw. The composer turns the draw into a panel
with pick() from the feet it really has at that moment (so the walk never drifts out of phase after a user pattern)."""
import math,random

PAD=((0,2),(0,0),(1,1),(2,0),(2,2))   # DL UL C UR DR, the pump-single pad of ArrowVortex styles.txt
MAX_STEP_DIST=2.2;MAX_SPREAD_DIST=3.1;START=(0,4)   # feetPos = AE (DL, DR)
TOP=min(MAX_STEP_DIST,max(math.dist(a,b) for a in PAD for b in PAD))
SPACING=((1.,'4th'),(2/3,'6th'),(.5,'8th'),(1/3,'12th'),(.25,'16th'),(1/6,'24th'),(.125,'32nd'),(1/12,'48th'),(0,'64th+'))
# Difficulty by note spacing in ms (time, not beat: 8ths at 200 BPM are a 16th stream at 100): slow notes may travel,
# fast streams stay compact around the centre. Level shifts it a little.
DIFF_MS=((500,.75),(300,.62),(200,.52),(130,.42),(90,.32))
# On a pump pad the x rule alone lets both feet share a column (L DL + R UL: standing sideways, 90 deg) on ~27% of
# steps; official charts turn far less (none at 1-5). Those options get this weight: ~1.5% / 3.5% / 5% of steps.
def side_weight(level):return 0. if level<6 else .06 if level<=12 else .1 if level<=17 else .14

def dist(a,b):return math.dist(PAD[a],PAD[b])

def spacing_name(beats):return next(n for b,n in SPACING if beats>=b-1e-3)

def difficulty(gap_ms,level):
    pts=DIFF_MS
    if gap_ms>=pts[0][0]:d=pts[0][1]
    elif gap_ms<=pts[-1][0]:d=pts[-1][1]
    else:
        (a,da),(b,db)=next((p,q) for p,q in zip(pts,pts[1:]) if p[0]>=gap_ms>=q[0])
        d=db+(da-db)*(gap_ms-b)/(a-b)
    return min(.9,max(.15,d+(level-14)*.015))

def _reps(seq,lane):
    n=0
    for l in seq:
        if l!=lane:break
        n+=1
    return n

def pick(pos,f,u,d,side,max_col=3,max_box=2,start=None,recent=()):
    """ArrowVortex FootPlanner::getNextCol for foot f (0 L, 1 R) from feet pos=[L,R], with draw u in [0,1).
    max_col / max_box: the dialog's "Single column" / "Paired columns" repetition limits; recent: panels stepped so far
    (feet alternate, so every second one is this foot's); start: the section's first foot (unused here)."""
    target=.2+(TOP-.2)*d;bias=abs(d*2-1);o=1-f;xo=PAD[pos[o]][0]
    lo,hi=(0,xo) if f==0 else (xo,9)
    w=[0.]*5;sd=[0.]*5
    for c in range(5):
        if c==pos[o] or not lo<=PAD[c][0]<=hi:continue
        s=dist(pos[f],c)
        if s>MAX_STEP_DIST or dist(pos[o],c)>MAX_SPREAD_DIST:continue
        w[c]=1. if PAD[c][0]!=xo else side;sd[c]=s
    rf,ro=_reps(recent[-2::-2],pos[f]),_reps(recent[-1::-2],pos[o])
    if rf>=max_col or (rf>=max_box and ro>max_box):w[pos[f]]=0.
    st=max(.1,target-.6)   # (ArrowVortex also steers by the running average step; ~0 here, the composer has no such state)
    for c in range(5):
        if w[c]>0:w[c]+=(w[c]/(.1+abs(max(.1,sd[c]-.6)-st))-w[c])*bias
    tot=sum(w)
    if not tot:return pos[f]   # boxed in (L DL with R UL, moving L): ArrowVortex re-steps the same panel
    x=u*tot
    for c in range(5):
        if w[c]>0:
            x-=w[c]
            if x<0:return c
    return max(range(5),key=lambda c:w[c])

def sections(events,rest_beats=1.):
    """Runs of notes split at rests (a beat or more, and well over the running spacing) or at a jump in spacing, each with its spacing in beats and ms."""
    out=[];cur=[events[0]] if events else []
    for a,b in zip(events,events[1:]):
        g=b['beat']-a['beat'];prev=cur[-1]['beat']-cur[-2]['beat'] if len(cur)>=2 else g
        if (g>=rest_beats-1e-6 and g>1.8*prev) or (len(cur)>=4 and not .55<g/max(prev,1e-6)<1.8):out.append(cur);cur=[]
        cur.append(b)
    if cur:out.append(cur)
    res=[]
    for s in out:
        gb=sorted(b['beat']-a['beat'] for a,b in zip(s,s[1:])) or [1.];gm=sorted(b['ms']-a['ms'] for a,b in zip(s,s[1:])) or [600.]
        res.append((s,gb[len(gb)//2],gm[len(gm)//2]))
    return res

def draws(events,level,seed,fixed):
    """Every section gets its own dialog settings, so each chart comes out different: the spacing is the original's,
    the difficulty follows its density (gradually: each section moves 70% of the way from the previous one, with a
    little seeded variation), "Single column" 1-3 / "Paired columns" 1-2 and the starting foot (after a rest) are drawn per section.
    fixed: indices stronger sources already hold. Returns ({index: (u, difficulty, side, single, paired, start foot)},
    section log)."""
    rng=random.Random(f'vortex{seed}');out={};log=[];side=side_weight(level);prev=None;last=None;lastgb=0.
    for sec,gb,gm in sections(events):
        g=sec[0]['beat']-last['beat'] if last else 9;rest=g>=1-1e-6 and g>1.8*lastgb;last=sec[-1];lastgb=gb   # the foot restarts only after a rest
        d=min(.9,max(.15,difficulty(gm,level)+rng.uniform(-.06,.06)));d=d if prev is None else prev+.7*(d-prev);prev=d
        col=rng.choices((1,2,3),(1,2,3))[0];box=min(col,rng.choice((1,2)));start=1 if rng.random()<.6 else 0
        log.append((sec[0]['index'],len(sec),spacing_name(gb),round(gm),round(d,2),col,box,'RL'[1-start]))
        for i,e in enumerate(sec):
            u=rng.random()
            if e['index'] not in fixed and len(e['lanes'])==1 and not e['holds']:out[e['index']]=(u,d,side,col,box,start if i==0 and rest else None)
    return out,log

if __name__=='__main__':
    ev=[dict(index=i,beat=i/4,ms=1000+i*100.,lanes=[0],holds=[]) for i in range(2000)]
    dr,log=draws(ev,18,1,set());pos=list(START);f=1;seq=[];side=0
    for i in range(2000):
        c=pick(pos,f,*dr[i],recent=tuple(seq));assert c!=pos[1-f] and dist(pos[f],c)<=MAX_STEP_DIST   # never DL<->UR
        pos[f]=c;assert PAD[pos[0]][0]<=PAD[pos[1]][0],pos   # never crossed
        side+=PAD[pos[0]][0]==PAD[pos[1]][0];seq.append(c);f=1-f
    assert .02<side/2000<.09,side
    assert all(pick([0,4],0,u/10,.5,0.) in (0,1,2) for u in range(10))   # L from DL, R on DR: stay, UL or C
    assert pick([0,4],0,.0,.1,0.,3,2,None,(0,4,0,4))==0 and pick([0,4],0,.0,.1,0.,1,1,None,(0,4,0,4))!=0   # Single column limit
    q=[dict(index=i,beat=float(i),ms=1000+i*500.,lanes=[0],holds=[]) for i in range(40)]
    assert len(sections(q))==1 and sum(x[5] is not None for x in draws(q,4,1,set())[0].values())==1   # quarters: one section
    print('sections',log[:2],'side %.3f'%(side/2000),'panels',seq[:24]);print('VORTEX_OK')
