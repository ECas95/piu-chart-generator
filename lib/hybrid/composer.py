"""Deterministic phrase/contact composer.

Reimplementation combining the project's conservative geometry with v3.5.1's
phrase/action separation. No song names, learned weights, fixed offsets, hidden
onset omissions, hold budgets, or automatic hold-to-tap repairs.
"""
from __future__ import annotations
from dataclasses import dataclass
from collections import Counter, defaultdict
from itertools import permutations, combinations
import math, hashlib, os
from .musical import preferences
from . import vortex as av
from .skill_graph import annotate, skill_report
from .pose_safety import stance_yaw, evolve
from .recovery import step as recovery_step, append_history, valid_bracket

SINGLE=((-1.,-1.),(-1.,1.),(0.,0.),(1.,1.),(1.,-1.))
DOUBLE=tuple((x-1.5,y) for x,y in SINGLE)+tuple((x+1.5,y) for x,y in SINGLE)

class NoRoute(ValueError):
    def __init__(self,event,reason):
        self.event=event;self.reason=reason
        super().__init__(f"row {event['index']} beat {event['beat']:.8f} ms {event['ms']:.6f}: {reason}")

@dataclass(slots=True)
class Node:
    pos:tuple; times:tuple; holds:tuple; last:int; last_ms:float
    recent:tuple; releases:tuple; cost:float; reduced:int; parent:object
    event:object; actions:tuple; setups:tuple=()
    turn_trace:tuple=(); source_trace:tuple=()
    recovery:object=None; contact_history:tuple=(); recovery_event:str=""

def _h(seed,*items):
    return int.from_bytes(hashlib.blake2s(repr((seed,items)).encode(),digest_size=8).digest(),'little')/2**64

def phrase_plan(events, tier):
    groups=defaultdict(list)
    for e in events:groups[int(e['beat']//8)].append(e)
    rows=[]
    for q,es in sorted(groups.items()):
        gaps=[b['ms']-a['ms'] for a,b in zip(es,es[1:])]
        signature=tuple(round(b['beat']-a['beat'],6) for a,b in zip(es,es[1:]))
        density=len(es)/8
        intent='anchor' if any(e['holds'] for e in es) else 'flow' if gaps and min(gaps)<180 else 'groove'
        rows.append({'start':q*8,'end':q*8+8,'intent':intent,'onsets':len(es),'density_per_beat':density,
                     'signature':hashlib.sha256(repr(signature).encode()).hexdigest()[:16],
                     'tier':tier})
    return rows

def select(events,tier):
    if tier=='HARD':return list(events),[]
    ratio={'MEDIUM':.72,'EASY':.42}[tier];out=[];ledger=[]
    groups=defaultdict(list)
    for e in events:groups[int(e['beat']//8)].append(e)
    for _,es in sorted(groups.items()):
        options=[]
        for div in (1,2,3,4,6,8,12,24):
            keep=[e for e in es if e['holds'] or abs(e['beat']*div-round(e['beat']*div))<1e-4]
            if not keep:continue
            options.append((abs(len(keep)/len(es)-ratio)+div*.001,div,keep))
        keep=min(options,key=lambda a:a[:2])[2] if options else [es[0]]
        ids={e['index'] for e in keep};out.extend(keep)
        for e in es:
            if e['index'] not in ids:ledger.append({'kind':'OMIT_ONSET','index':e['index'],'beat':e['beat'],
                'source_lanes':e['lanes'],'reason':'whole-phrase rhythmic subdivision','tier':tier})
    return sorted(out,key=lambda e:e['index']),ledger

USER_FOLLOW_BONUS=3.
VARIANT=os.environ.get('PIU_VARIANT','A').upper()   # test variants: A safe, B official crossings, C no crossings
OFFICIAL_MIN=5
_OFFICIAL=None

def transit_yaw(before,after):
    """Largest |stance angle| while the feet travel in straight lines from one stance to the next (Single)."""
    worst=0.
    for k in range(1,8):
        t=k/8;p=[(SINGLE[b][0]+(SINGLE[a][0]-SINGLE[b][0])*t,SINGLE[b][1]+(SINGLE[a][1]-SINGLE[b][1])*t) for b,a in zip(before,after)]
        if p[0]!=p[1]:worst=max(worst,abs(math.degrees(math.atan2(-(p[1][1]-p[0][1]),p[1][0]-p[0][0]))))
    return worst

def official_context(order,k,lanes_of):
    """The panels of 3 notes before and 2 after step k (single taps, mirror-normalized) appear >= OFFICIAL_MIN times
    around a crossover in official FIESTA 2 / PRIME / PRIME 2 / XX Single charts (official_cross_contexts.json)."""
    global _OFFICIAL
    if _OFFICIAL is None:
        import json
        from pathlib import Path
        p=Path(__file__).parent/'official_cross_contexts.json'
        _OFFICIAL={tuple(json.loads(a)):b for a,b in json.loads(p.read_text()).items()} if p.exists() else {}
    if k<3 or k+2>=len(order):return False
    win=[lanes_of[o] for o in order[k-3:k+3]]
    if any(len(w)!=1 for w in win):return False
    seq=tuple(w[0] for w in win);return _OFFICIAL.get(min(seq,tuple(4-l for l in seq)),0)>=OFFICIAL_MIN

def compose(events,columns=5,level=20,tier='HARD',beam=40,seed=0,travel_speed=None,
            pose_policy='balanced', skill_weight=4.0, recovery_policy='strict', skip_conflicts=0, user_patterns=True):
    # User patterns first. Where they box the route in, the blocks before that spot are composed with the official
    # motifs instead (16 more notes back each time the same spot fails again, up to 64); if that is not enough the
    # whole chart is. Only then may a caller start omitting notes.
    # v3.1 (user 2026-10-31, End of the Moonlight S18 left the player backwards): a user pattern counts only where it
    # is followed note for note. Where the composer leaves it, fragments of different patterns glue into crossovers
    # nobody validated. A chained stretch the composer leaves is tried once mirrored (that swaps the feet: usually the
    # chart arrives there on the other foot), then composed without user patterns.
    # Variant B: also crossings the official charts justify (their 6-note context, 3 before / 2 after, appears at least
    # OFFICIAL_MIN times in FIESTA 2 / PRIME / XX); a spot that fails gets no crossing (no_cross) and is composed again.
    if user_patterns is True and columns==5:
        blocked,flipped,no_cross=frozenset(),frozenset(),frozenset();at={e['index']:i for i,e in enumerate(events)};last=None;back=0;rounds=0
        lanes_of={e['index']:e['lanes'] for e in events}
        for _ in range(40):
            try:r=compose(events,columns,level,tier,beam,seed,travel_speed,pose_policy,skill_weight,recovery_policy,skip_conflicts,user_patterns=(blocked,flipped,no_cross))
            except NoRoute as ex:
                x=ex.event['index'];back=back+16 if x==last else 0;last=x
                if x not in at or back>64:break
                blocked|={e['index'] for e in events[max(0,at[x]-back):at[x]+1]};continue
            order=[p['index'] for p in r['plan']];pos={ix:i for i,ix in enumerate(order)}
            want=lambda h:sorted(h if isinstance(h,tuple) else (h,))
            foot_ok=lambda ix:r['user_feet'].get(ix,2)==2 or [a[1] for a in r['plan'][pos[ix]]['actions']]==[r['user_feet'][ix]]
            followed={ix for ix,h in r['user_hints'].items() if ix in pos and sorted(a[0] for a in r['plan'][pos[ix]]['actions'])==want(h) and foot_ok(ix)}
            # every crossed stance (>90 deg) must sit inside a pattern followed note for note: 3 notes before, 2 after
            stance=[0,4];unsafe=[];entry_yaw={}
            # variant F: a twist dropped into the walk has no pattern before it; it is safe when the whole twist is
            # followed note for note and the player enters it facing front (<=60 deg)
            seg_of={ix:sg for sg in r['user_segments'] for ix in sg}
            whole_twist=lambda k:order[k] in seg_of and all(ix in followed for ix in seg_of[order[k]]) and entry_yaw.get(seg_of[order[k]][0],180)<=60+1e-7
            for k,item in enumerate(r['plan']):
                before=list(stance)
                (bx,by),(cx,cy)=SINGLE[before[0]],SINGLE[before[1]];entry_yaw[item['index']]=abs(math.degrees(math.atan2(-(cy-by),cx-bx)))
                for lane,foot,_ in item['actions']:stance[foot]=lane
                if transit_yaw(before,stance)>135+1e-7:unsafe.append(k);continue   # the moving foot passes behind
                (lx,ly),(rx,ry)=SINGLE[stance[0]],SINGLE[stance[1]]
                if stance[0]!=stance[1] and abs(math.degrees(math.atan2(-(ry-ly),rx-lx)))>90+1e-7 and not all(o in followed for o in order[max(0,k-3):k+3]):
                    if not (VARIANT=='B' and official_context(order,k,lanes_of)) and not (VARIANT=='F' and whole_twist(k)):unsafe.append(k)
            # a stretch the route enters on the other foot is not followed from its start: try it mirrored once
            entry=[s for s in r['user_segments'] if s[0] not in flipped and sum(ix in followed for ix in s[:8])<min(6,len(s))]
            if not unsafe and not entry:return r
            rounds+=1
            if rounds>16:
                if not unsafe:return r
                break
            flipped|={s[0] for s in entry}
            if VARIANT=='B':no_cross|={order[k] for k in unsafe}
            else:blocked|={order[j] for k in unsafe for j in range(max(0,k-7),min(len(order),k+8))}
        user_patterns=False
    if columns not in (5,10) or not 1<=level<=28:raise ValueError('Single/Double level1..28 required')
    tier=tier.upper()
    if tier not in ('EASY','MEDIUM','HARD'):raise ValueError('tier EASY/MEDIUM/HARD required')
    if not events:raise ValueError('no source events')
    if pose_policy not in ('strict','guarded','balanced','soft','off'):raise ValueError('pose_policy must be strict, balanced or off')
    if recovery_policy not in ('strict','off'):raise ValueError('recovery_policy must be strict or off')
    if not 4<=beam<=256:raise ValueError('beam must be4..256')
    coords=SINGLE if columns==5 else DOUBLE;span=2.9 if columns==5 else 3.05
    speed=float(travel_speed if travel_speed is not None else 5+level*.10)
    if not math.isfinite(speed) or speed<=0:raise ValueError('travel_speed must be finite and positive')
    if not math.isfinite(skill_weight) or skill_weight<0 or skill_weight>5:
        raise ValueError('skill_weight must be within 0..5')
    chosen,ledger=select(events,tier);phrases=phrase_plan(chosen,tier)
    skills=annotate(chosen);skill_summary=skill_report(chosen,skills)
    hints,motif_receipt=preferences(chosen,columns,level,seed,user=tuple(user_patterns[:2]) if isinstance(user_patterns,tuple) else bool(user_patterns))
    no_cross=user_patterns[2] if isinstance(user_patterns,tuple) and len(user_patterns)>2 else frozenset()
    managed=isinstance(user_patterns,tuple)   # composed under the wrapper's post-checks
    # User-validated patterns (musical.user_patterns) contain short crossovers: only a step that lands exactly on
    # its hinted panel may cross up to 135 degrees; every other step keeps the 60-degree / anti-spin rules.
    user_ix=frozenset(motif_receipt.get('user_indices',()));user_segments=motif_receipt.get('user_segments',[])
    user_feet=motif_receipt.get('user_feet',{})   # v3.1: the foot each user-pattern note was validated with
    vortex=motif_receipt.get('vortex_draws',{})   # variant D: ArrowVortex walk (draws turned into panels from the real feet)
    motif_receipt={k:v for k,v in motif_receipt.items() if k not in ('user_indices','user_segments','user_feet')}
    # v363 skill balance vs native charts of the same band: easier tiers keep
    # only a share of source chords as jumps (DDR sources are chord-heavy).
    chord_share=sum(len(e['lanes'])>=2 and not e['holds'] for e in chosen)/len(chosen)
    keep_jump=1. if tier=='HARD' else min(1.,{'EASY':.14,'MEDIUM':.10}[tier]/max(chord_share,1e-9))
    phrases_by_start={p['start']:p for p in phrases}
    end_info={int(end):(e['hold_ends_ms'][int(end)],e['hold_ends_beat'][int(end)]) for e in events for end,_ in e['holds']}
    pos=(0,4) if columns==5 else (3,6);start=chosen[0]['ms']-2000
    states=[Node(pos,(start,start),(-1,-1),-1,-math.inf,(),(),0.,0,None,None,())]
    expansions=0
    _dtab=[[math.dist(coords[a],coords[b]) for b in range(columns)] for a in range(columns)]  # v363 speed
    distance=lambda a,b:_dtab[a][b]
    for number,event in enumerate(chosen):
        ix,bt,now=event['index'],event['beat'],event['ms'];holds=sorted(event['holds'])
        # v363 speed: per-event values formerly recomputed for every candidate
        pref_default=int(_h(seed,int(bt//8)//2,int(bt*4)%32)*columns)%columns;jump_draw=_h(seed,'jump',ix)
        if len(holds)>2:raise NoRoute(event,f'{len(holds)} simultaneous source holds exceed the current two-independent-contact model; bracket backend is not calibrated')
        if columns==10 and tier=='HARD' and len(event['lanes'])>2:
            if not event['holds'] and skip_conflicts>0:  # v363 speed: omit in-pass instead of a full recompose
                skip_conflicts-=1
                ledger.append({'kind':'OMIT_ONSET','index':ix,'beat':bt,'source_lanes':event['lanes'],'reason':'v363: Double HARD chord of 3+ heads has no calibrated bracket solver','tier':tier})
                continue
            raise NoRoute(event,f"{len(event['lanes'])} source heads need a calibrated bracket solver; none are discarded")
        candidates=[]
        # A foot may silently reposition BETWEEN existing BMS attacks. This is
        # NOT a new chart note: it is a foot-contact plan entry (`setups`).
        # Only allow it during a committed twist, with enough time and with
        # the opposite foot available as support. Existing independent replay
        # must still approve both the silent setup and the following attack.
        expanded=[(st,st,()) for st in states]
        if recovery_policy=='strict' and columns==5:
            for original in states:
                pending=original.recovery
                if pending is None or pending.phase!='NEXT':continue
                f=pending.core_foot
                if original.holds[f]>=0 or original.holds[1-f]>=0:continue
                gap=now-original.last_ms
                if gap<175 or gap>1700:continue
                when=original.last_ms+.75*gap
                oldyaw=stance_yaw(original.pos,coords)
                for target in range(columns):
                    if target in original.pos:continue
                    dist=distance(original.pos[f],target)
                    elapsed=when-original.times[f]
                    if dist>.75+speed*max(elapsed,0)/1000+1e-7:continue
                    newpos=list(original.pos);newpos[f]=target
                    if distance(*newpos)>span+1e-7:continue
                    yaw=stance_yaw(newpos,coords)
                    if abs(yaw)>60+1e-7 or (when-original.last_ms<900 and abs(yaw-oldyaw)>90+1e-7):continue
                    nt,pc,err=evolve(original.turn_trace,oldyaw,yaw,when,original.last_ms,
                                     policy=pose_policy)
                    if err:continue
                    newtimes=list(original.times);newtimes[f]=when
                    from dataclasses import replace
                    virtual=replace(original,pos=tuple(newpos),times=tuple(newtimes),
                                    turn_trace=nt,cost=original.cost+1.25+.26*dist*dist+pc,
                                    setups=((f,target,when),))
                    expanded.append((virtual,original,((f,target,when),)))
        for state,parent_state,setup_actions in expanded:
            pinned=list(state.holds);times=list(state.times);releases=list(state.releases)
            for f,end in enumerate(pinned):
                if end>=0 and end<=ix:
                    tail_ms,tail_bt=end_info[end];times[f]=max(times[f],tail_ms)
                    releases.append((state.pos[f],tail_ms,tail_bt,f));pinned[f]=-1
            releases=tuple(r for r in releases if now-r[1]<350-1e-7 and bt-r[2]<.5-1e-7)
            released_lanes={r[0] for r in releases}
            # v363 speed: per-state values formerly recomputed for every candidate
            prev_sorted=tuple(sorted(a[0] for a in state.actions)) if state.event is not None and now-state.last_ms<300-1e-7 else None
            _rec=state.recent;_l3=_rec[-3:];gram_next={}
            for _i in range(max(0,len(_rec)-3)):
                _w=_rec[_i:_i+4]
                if _w[:3]==_l3:gram_next[_w[3]]=gram_next.get(_w[3],0)+1
            free=[f for f in (0,1) if pinned[f]<0]
            maxcount=min(2,len(event['lanes']),len(free))
            mincount=max(1,len(holds))
            counts=[len(event['lanes'])] if columns==10 and tier=='HARD' else list(range(mincount,maxcount+1))
            for count in counts:
                if count>maxcount:continue
                # Hold identities precede taps. All hold/tap mixed rows remain
                # possible; reduction changes only individual excess taps.
                source_lanes=[lane for _,lane in holds]+[l for l in event['lanes'] if l not in {x[1] for x in holds}]
                ends=[end for end,_ in holds]+[-1]*(count-len(holds))
                foot_options=list(permutations(free,count))
                # Same-foot heel/toe bracket is an explicitly bounded recovery
                # option for an existing two-head BMS chord; NEVER invent a note.
                # The template requires one right foot on CE+DR or its left mirror.
                if (columns==5 and level>=17 and count==2 and not holds and
                    state.recovery is not None and state.recovery.phase=='NEXT'):
                    foot=1 if state.recovery.side==3 else 0
                    if foot in free:foot_options.append((foot,foot))
                for feet in foot_options:
                    bracket=(count==2 and feet[0]==feet[1])
                    lane_options=( ((2,4),) if feet[0]==1 else ((2,0),) ) if bracket else permutations(range(columns),count)
                    for lanes in lane_options:
                        if bracket and not valid_bracket(tuple((l,f,-1) for l,f in zip(lanes,feet)),level=level):continue
                        if bracket and state.pos[1-feet[0]] in lanes:continue
                        if released_lanes and not released_lanes.isdisjoint(lanes):continue
                        if prev_sorted is not None and tuple(sorted(lanes))==prev_sorted:continue
                        positions=list(state.pos);nexttimes=list(times);nextholds=list(pinned);cost=0.;ok=True
                        # The right/left bracket treats both contact panels as
                        # one foot. The last lane is its support anchor; the
                        # other is simultaneous heel/toe contact only.
                        for slot,(f,lane) in enumerate(zip(feet,lanes)):
                            if bracket and slot==0:continue
                            if pinned[1-f]>=0 and lane==state.pos[1-f]:ok=False;break
                            dt=now-times[f];d=distance(state.pos[f],lane)
                            if dt < -1e-6 or d>.75+speed*max(dt,0)/1000+1e-7:ok=False;break
                            # On verified BMS A-B-A-B source drills, the same
                            # foot may revisit its panel after ~222ms at 135BPM.
                            # A universal 300ms rule erased these motifs.
                            # Never relax other rapid repeats or 100ms drills.
                            repeat_floor=(180. if columns==5 and level>=17 and skills.get(ix)=='DRILL' else 300.)
                            # v3.1: a user pattern's drill (the foot returns to its panel while the other foot steps
                            # in between, e.g. C UL DL UL C) is validated at 16ths: 200 ms re-steps
                            if ix in user_ix and lane==hints.get(ix) and f==user_feet.get(ix):repeat_floor=150.
                            if lane==state.pos[f] and dt<repeat_floor-1e-7:ok=False;break
                            positions[f]=lane;nexttimes[f]=now;nextholds[f]=ends[slot]
                            cost+=.26*d*d/max(.3,min(1.5,dt/400))
                        if bracket:cost+=1.1  # heel/toe reach + reduced confidence
                        if not ok or positions[0]==positions[1]:continue
                        l,r=(coords[p] for p in positions)
                        facing=abs(math.degrees(math.atan2(-(r[1]-l[1]),r[0]-l[0])))
                        # a row-pattern hint is a tuple (hold lanes first, like the slots here): the holds must land on
                        # their panels and the taps on the rest
                        want=hints[ix] if isinstance(hints.get(ix),tuple) else (hints.get(ix),);nh=len(holds)
                        # v3: crossovers from level 6, as official charts (the gate keeps 1-5 front-facing, 6-12 to 1-2 steps)
                        wf=user_feet.get(ix,2)   # v3.1: the panel AND the foot it was validated with
                        following=(level>=6 and ix in user_ix and count==len(want) and tuple(lanes[:nh])==want[:nh] and set(lanes[nh:])==set(want[nh:])
                                   and (wf==2 or (count==1 and feet[0]==wf)))
                        following=following and ix not in no_cross
                        # variant B: any step may cross (<=135) under the wrapper's official-context check, at a cost
                        cross_free=following or (VARIANT=='B' and managed and level>=6 and ix not in no_cross and count==1)
                        # variant D: the ArrowVortex walk may stand sideways (both feet in one column, 90 deg) where it says so
                        vx=None
                        if ix in vortex and count==1:   # feet alternate from the last step; a section after a rest starts on its own foot
                            vd=vortex[ix];vf=vd[5] if vd[5] is not None else 1-state.last if state.last in (0,1) else 1
                            vx=(av.pick(list(state.pos),vf,*vd,recent=state.recent),vf)
                        side_ok=level>=6 and vx==(lanes[0],feet[0])
                        if facing>(135. if cross_free else 90. if side_ok else 60.)+1e-7 or distance(*positions)>span+1e-7:continue
                        cross_free=following or (cross_free and facing>60+1e-7)
                        if cross_free and not following:cost+=1.2
                        old_l,old_r=(coords[p] for p in state.pos)
                        old_facing=math.degrees(math.atan2(-(old_r[1]-old_l[1]),old_r[0]-old_l[0]))
                        new_facing=math.degrees(math.atan2(-(r[1]-l[1]),r[0]-l[0]))
                        last_pose_ms=setup_actions[-1][2] if setup_actions else state.last_ms
                        if not cross_free and now-last_pose_ms<900 and abs(new_facing-old_facing)>90+1e-7:continue
                        # v3: levels 6-12 keep crossovers to a single step, as official charts (88% of their runs)
                        if level<=12 and facing>90+1e-7 and abs(old_facing)>90+1e-7:continue
                        turn_trace,turn_penalty,turn_error=evolve(
                            state.turn_trace,old_facing,new_facing,now,last_pose_ms,
                            policy='off' if cross_free else pose_policy)  # v363: anti-spin guard also in Double
                        if turn_error:continue
                        cost+=turn_penalty
                        # Two new holds may not pin both feet across any required
                        # later attack. This is lookahead, not a hold deletion.
                        if all(h>=0 for h in nextholds) and number+1<len(chosen) and chosen[number+1]['index']<min(nextholds):continue
                        # v363 strict parity: a player alternates single steps.
                        # Same foot twice only as a jack (same panel) or while the
                        # other foot is held. The v362 post-release window allowed
                        # 160ms same-foot chains that players read as spins.
                        if count==1 and state.last==feet[0]:
                            other=1-feet[0]
                            # Narrow exception: the other foot released a hold <=300ms ago
                            # and >=200ms passed (v362 allowed 160ms chains -> spins).
                            just_released=any(r[3]==other and now-r[1]<=300 for r in releases) and now-state.last_ms>=200
                            if pinned[other]<0 and lanes[0]!=state.pos[feet[0]] and not just_released:continue
                            cost+=.5
                        q=int(bt//8);phase=(bt%8)/8
                        # Native phrases propose vocabulary; phrase intent changes
                        # style costs without forcing source rhythm or foot parity.
                        preferred=vx[0] if vx else hints.get(ix,pref_default)
                        # v363: native motifs are parity-free lane lists; mirror a
                        # hinted panel onto the stepping foot's own side so the
                        # motif shape survives without crossing (Single only).
                        # User patterns keep their crossovers: never mirrored per step, and followed firmly.
                        if columns==5 and count==1 and ix not in user_ix and ix not in vortex and coords[preferred][0]*(1 if feet[0]==0 else -1)>0:
                            preferred=4-preferred
                        if ix in user_ix and count==1 and user_feet.get(ix,2)<2 and feet[0]!=user_feet[ix]:cost+=1.5   # wrong foot for the pattern
                        if following:cost-=USER_FOLLOW_BONUS   # v3.1: keep the validated route alive in the beam
                        if isinstance(preferred,tuple):cost+=2.*sum(min(distance(p,q) for p in lanes) for q in preferred)+(0. if following else 1.5)
                        else:cost+=(2. if ix in user_ix else 2. if ix in vortex else .65)*min(distance(p,preferred) for p in lanes)
                        if vx and feet[0]!=vx[1]:cost+=1.2   # its walk alternates feet
                        intent=phrases_by_start[q*8]['intent']
                        if intent=='flow' and count==1 and state.last!=feet[0]:cost-=.15
                        if intent=='groove' and count==2 and abs(bt-round(bt))<1e-4:cost-=.20
                        if intent=='anchor' and any(end>=0 for end in nextholds):cost+=.015*facing
                        history=state.recent
                        if count==1:
                            lane=lanes[0];cost+=.28*history[-12:].count(lane)
                            if len(history)>=3 and history[-3]==history[-1] and history[-2]==lane and vx!=(lane,feet[0]):cost+=1.6   # (an ArrowVortex anchor within its limits is fine)
                            cost+=.75*gram_next.get(lane,0)
                        if phase>=.75 and positions[0] in (0,1) and positions[1] in (3,4):cost-=.18
                        # BMS/RESPECT source keys determine which skill can
                        # be attempted; native corpus notes are only soft priors.
                        # The same source key need not map to a fixed Pump pad.
                        # We reward source ABAB drills with a stable two-panel
                        # motif, while never overriding anti-spin and holds.
                        skill=skills[ix]
                        source_key=event['lanes'][0] if len(event['lanes'])==1 and not event['holds'] else None
                        past=state.source_trace
                        if count==1 and source_key is not None:
                            lane=lanes[0]
                            matching=[(k,p) for k,p in past if k==source_key]
                            if skill=='DRILL':
                                if matching and matching[-1][1]!=lane:
                                    cost+=skill_weight*.95
                                if len(past)>=2 and past[-1][0]!=source_key and past[-1][1]==lane:
                                    cost+=skill_weight*1.15
                                if state.last==feet[0]:cost+=skill_weight*.3
                            elif skill=='RUN':
                                if state.last==feet[0]:cost+=skill_weight*1.0
                                if history and history[-1]==lane:cost+=skill_weight*.5
                            elif skill=='REPEAT':
                                # Repeated source key is *not* forced into an
                                # impossible same-panel footswitch.
                                if matching and matching[-1][1]!=lane:cost+=skill_weight*.18
                        if skill=='CHORD' and count==2:cost-=skill_weight*.45
                        if keep_jump<1. and len(event['lanes'])>=2 and not holds:
                            if jump_draw>=keep_jump:cost+=4.5 if count==2 else -2.6
                        if columns==10 and count==1:
                            # Native Doubles stay on one pad for a while and use the
                            # centre panels less than a pure shortest-move planner.
                            if lanes[0] in (2,7):cost+=.3
                            if history and (history[-1]<5)!=(lanes[0]<5) and now-state.last_ms<300:cost+=.6
                        if skill=='HOLD' and count>=len(holds):cost-=skill_weight*.25
                        # A phrase boundary is a recovery opportunity. Its
                        # physical safety constraints remain hard throughout.
                        if abs(bt%8-7.5)<.26:
                            cost+=skill_weight*.30*abs(new_facing)/45.
                        # v365: a jack (same foot, same panel) is cheap in movement, so the planner
                        # overused it (90% of easy phrases vs 53% official). Only free when the
                        # ORIGINAL chart repeats the same key there.
                        if count==1 and lanes[0]==state.pos[feet[0]] and not (past and source_key is not None and past[-1][0]==source_key):cost+=.9
                        next_source=(past+(((source_key,lanes[0]),) if source_key is not None and count==1 else ())) [-8:]
                        actions=tuple((lane,f,ends[k]) for k,(f,lane) in enumerate(zip(feet,lanes)))
                        next_recovery, recovery_event, recovery_error=recovery_step(
                            state.recovery,state.contact_history,actions,bt,now,level=level,
                            enabled=(columns==5 and recovery_policy=='strict'))
                        if recovery_error:continue
                        # An unresolved core at the final BMS attack cannot be
                        # considered a complete skill, even with no next note.
                        if number==len(chosen)-1 and next_recovery is not None:continue
                        if recovery_event=='TWIST_CORE_COMMITTED':cost+=1.5
                        if recovery_event.startswith('FRONT_'):cost-=2.0
                        next_history=append_history(state.contact_history,actions,bt,now)
                        reduced=len(event['lanes'])-count
                        # Source chords are salient, but can be adapted in Single.
                        # Make reductions visible and carry alternatives in beam.
                        cost+=reduced*3.5
                        candidates.append(Node(tuple(positions),tuple(nexttimes),tuple(nextholds),feet[0] if count==1 else -1,now,
                            (history+lanes)[-24:],releases,state.cost+cost,state.reduced+reduced,parent_state,event,actions,setup_actions,turn_trace,next_source,
                            next_recovery,next_history,recovery_event))
                        expansions+=1
        if not candidates:
            # v363 speed: omit a boxed-in free onset in the same pass (ledgered)
            # instead of restarting the whole chart; hold heads still raise.
            if not event['holds'] and skip_conflicts>0:
                skip_conflicts-=1
                ledger.append({'kind':'OMIT_ONSET','index':ix,'beat':bt,'source_lanes':event['lanes'],'reason':'v363 physical conflict: no legal two-foot route at this onset','tier':tier})
                continue
            raise NoRoute(event,'bounded beam found no legal route preserving all selected onsets and all holds; this is not an impossibility proof')
        # Both per-foot time and pinned owner are part of the state. Keep a small
        # diversified quota by current cardinality to avoid an all-jump frontier.
        unique={}
        for st in sorted(candidates,key=lambda s:(s.cost,s.pos,s.times,s.holds,s.last)):
            key=(st.pos,st.times,st.holds,st.last,st.recent,st.releases,st.recovery,st.contact_history) if recovery_policy=='strict' and columns==5 else (st.pos,st.times,st.holds,st.last,st.recent,st.releases)
            if key not in unique:unique[key]=st
        ordered=list(unique.values());states=ordered[:beam]
        # Keep non-committed alternatives alive until a committed twist has
        # an actual exit. Otherwise a low-cost core can consume the full beam,
        # making the next unrelated BMS note impossible to realize.
        if recovery_policy=='strict' and columns==5:
            safe=[x for x in ordered if x.recovery is None]
            reserve=min(max(4,beam//3),len(safe))
            if reserve and sum(x.recovery is None for x in states)<reserve:
                selected=safe[:reserve]
                ids={id(x) for x in selected}
                selected+= [x for x in ordered if id(x) not in ids][:beam-reserve]
                states=selected[:beam]
        if columns==5 and len(event['lanes'])>=2:
            for count in (1,2):
                diversity=[s for s in ordered if len(s.actions)==count][:max(2,beam//8)]
                for st in diversity:
                    if not any(st is x for x in states):states[-1:]=[st]+states[-1:];states.pop(-max(2,beam//4))
    winner=min(states,key=lambda s:(s.cost,s.pos));chain=[];node=winner
    while node.event is not None:chain.append(node);node=node.parent
    plan=[]
    for st in reversed(chain):
        e=st.event;plan.append({'index':e['index'],'actions':[list(a) for a in st.actions],
            'recovery_event':st.recovery_event,
            'setups':[list(x) for x in st.setups]})
        kept=set(l for _,l in e['holds'])
        taps=[l for l in e['lanes'] if l not in kept]
        kept.update(taps[:len(st.actions)-len(e['holds'])])
        for lane in e['lanes']:
            if lane not in kept:ledger.append({'kind':'REDUCE_CHORD_HEAD','index':e['index'],'beat':e['beat'],
                'source_lane':lane,'reason':'Single chord adapted to two feet; onset and all source holds retained','tier':tier})
    return {'plan':plan,'ledger':ledger,'phrases':phrases,'user_hints':{ix:hints[ix] for ix in user_ix},'user_feet':user_feet,'user_segments':user_segments,'metrics':{'beam':beam,'expansions':expansions,
        'cost':winner.cost,'travel_speed':speed,'source_onsets':len(events),'selected_onsets':len(chosen),
        'native_phrase_prior':motif_receipt,
        'output_heads':sum(len(x['actions']) for x in plan),'reduced_heads':sum(x['kind']=='REDUCE_CHORD_HEAD' for x in ledger),
        'geometry':'two-foot stance proxy with isolated experimental two-tap heel/toe recovery brackets; torso not observed',
        'anti_spin_policy':pose_policy if columns==5 else 'off',
        'recovery_policy':recovery_policy if columns==5 else 'off',
        'recovery_cores':sum(x.get('recovery_event')=='TWIST_CORE_COMMITTED' for x in plan),
        'recovery_exits':sum(x.get('recovery_event','').startswith(('FRONT_','SIDE_','BRACKET_')) for x in plan),
        'brackets_heel_toe_hypotheses':sum(len(x['actions'])==2 and x['actions'][0][1]==x['actions'][1][1] for x in plan),
        'silent_reposition_events':sum(len(x['setups']) for x in plan),
        'anti_spin_guard':columns==5 and pose_policy!='off',
        'skills':skill_summary,'skill_weight':skill_weight,
        'body_orientation_certified':False,
        'level_status':'requested design target; not a calibrated final rating'}}
