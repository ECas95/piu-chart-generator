"""Soft panel vocabulary from OFFICIAL PIU charts (v365 skill bank).

For every 8-onset phrase of the ORIGINAL chart: official motifs with the same rhythm
(exact beat gaps) and level band are ranked; motifs whose skill matches the original's
own key pattern (drill / run / staircase / anchor run / jack) are preferred, and reuse of
the same motif or the same skill in consecutive phrases is penalised for variety.
Hints are soft: the contact solver (parity, anti-spin gate) decides. Times never change.
"""
from collections import Counter
from pathlib import Path
import json, math, hashlib
from . import vortex

_BANKS=None;_INDEX={};_MEMO={};_SIM={};_USER=None
STRONG=('drill','run','staircase','anchor_run','jack')
USER_MIN_LEVEL=6    # v3: official charts turn from level 6 (59% of 6-12 charts), never at 1-5
PANEL={'DL':0,'UL':1,'C':2,'UR':3,'DR':4}

# v3 turn placement, measured on 1,566 official Single charts of FIESTA 2 / PRIME / PRIME 2 / XX (v3_research):
# share of steps beyond 45 deg per band (6-12, 13-17, 18+), and how much more likely a turn is than average by local
# intensity (2 s note count / the chart's 80th percentile, bins 0, .25, .5, .75, 1+), by rhythm, and on the first
# note after a rest of a beat or more.
TURN_TARGET=(.075,.12,.145)
TURN_INTENSITY=((.08,.18,.48,1.08,1.55),(.21,.66,.95,1.09,1.1),(.39,.86,1.12,.96,1.02))
TURN_RHYTHM={'16th':(.6,.73,.91),'8th':(1.49,1.35,1.21),'trip':(.43,1.34,1.34),'quarter':(.38,.67,.73),'other':(.18,.46,.68)}
TURN_RUN_START=(.33,.59,.65)
MAX_CROSS_RUN_LOW=1   # levels 6-12: official crossovers are 1 step (88%); 2+ only from 13
ONE_STEP_SHARE=.65    # 13+: official crossovers last 1 step 80% of the time -> prefer 1-step patterns this often
TWIST_GAP=16          # ... but not back to back: at least this many notes between two twists
VARIANT=__import__('os').environ.get('PIU_VARIANT','A').upper()   # A safe, B official crossings, C no crossings,
                      # D = A with the ArrowVortex stream planner instead of official motifs (vortex.py), E = that
                      # planner alone (no user patterns), to judge it by itself, F = E plus the allowed twists
TWIST_SHARE=.5        # user 2026-10-31: put the allowed twists (T*) in now and then, always complete: when a turn is
                      # wanted and a twist fits the junction (panel and foot), take a twist this often

def turn_band(level):return 0 if level<=12 else 1 if level<=17 else 2
# Variant F (user 2026-10-31: "E is perfect, add the allowed twists in all the different spacings, for variety, without
# leaving you backwards"): one whole twist about every this many notes per band (2 turning steps of 5: ~5% / 8% / 10%
# of steps, the official share), each spacing the song uses gets at least one, and none in bursts faster than this.
TWIST_EVERY=(40,24,18);TWIST_MIN_MS=80

def twist_hints(events,level,seed,blocked=frozenset(),flipped=frozenset()):
    """Variant F: the user's allowed twists (T*) dropped in whole on 5 single taps of one section, any spacing.
    Returns (hints, log, segments, feet) like row_hints."""
    tw=[(pid,seq) for pid,seq in user_patterns() if pattern_meta(pid)['twist'] and allowed(pattern_meta(pid),level)]
    hints={};feet={};segs=[];log=[]
    if not tw or level<USER_MIN_LEVEL:return hints,log,segs,feet
    every=TWIST_EVERY[turn_band(level)];used=Counter();got=Counter();since=every//2
    for sec,gb,gm in vortex.sections(events):
        name=vortex.spacing_name(gb);i=0
        while i<len(sec):
            win=sec[i:i+5]
            raw=hashlib.blake2s(repr((seed,'twist',win[0]['index'])).encode(),digest_size=4).digest()
            due=since>=every or (got[name]==0 and since>=TWIST_GAP)   # every spacing gets its twist
            if (len(win)==5 and due and gm>=TWIST_MIN_MS and raw[0]<160
                    and all(len(e['lanes'])==1 and not e['holds'] and e['index'] not in blocked for e in win)):
                low=min(used[pid] for pid,_ in tw);pool=[t for t in tw if used[t[0]]==low]
                pid,seq=pool[int.from_bytes(raw,'little')%len(pool)];g=bool(raw[1]&1)!=(win[0]['index'] in flipped)
                pf=pattern_meta(pid)['feet']
                for e,l,f in zip(win,seq,pf):hints[e['index']]=4-l if g else l;feet[e['index']]=1-f if g else f
                used[pid]+=1;got[name]+=1;segs.append([e['index'] for e in win]);log.append(f"{pid}{'m' if g else ''} {name}")
                since=0;i+=5;continue
            since+=1;i+=1
    return hints,log,segs,feet

def allowed(meta,level):
    if VARIANT=='C' and meta.get('crossovers',0):return False   # variant C: front-facing and twist patterns only
    return level>=USER_MIN_LEVEL and (level>=13 or meta.get('max_cross_run',0)<=MAX_CROSS_RUN_LOW)

def user_patterns():
    """User-validated Single panel sequences (user_patterns_single.json, played on a pad: never leave the player
    backwards), any length, valid with any rhythm."""
    return _user_bank()[0]

def user_row_patterns():
    """User-validated row patterns: (id, meta, steps); a step is (row, lanes with hold lanes first, {lane: end row}).
    Rows are 8ths; empty rows are rests."""
    return _user_bank()[1]

def pattern_meta(pid):return _user_bank()[2][pid]

def _user_bank():
    global _USER
    if _USER is None:
        p=Path(__file__).parent/'user_patterns_single.json';seqs,rows,meta=[],[],{}
        for u in json.loads(p.read_text('utf8'))['patterns'] if p.exists() else []:
            meta[u['id']]={k:u.get(k,0) for k in ('steps','turns','crossovers','max_cross_run')}
            meta[u['id']].update(start_foot=u.get('start_foot'),end_foot=u.get('end_foot'),feet=u.get('feet'),twist=u.get('kind','').startswith('twist'))
            if 'panels' in u:seqs.append((u['id'],[PANEL[x] for x in u['panels']]));continue
            steps=[]
            for r,items in enumerate(u['rows']):
                if not items:continue
                parts=[(PANEL[i.partition('~')[0]],i.partition('~')[2]) for i in items]
                ends={l:r+int(h) for l,h in parts if h}
                steps.append((r,tuple(sorted(l for l,_ in parts if l in ends))+tuple(sorted(l for l,_ in parts if l not in ends)),ends))
            rows.append((u['id'],meta[u['id']],steps))
        _USER=(seqs,rows,meta)
    return _USER

class TurnBudget:
    """Decides, for a stretch of the chart, whether a turning user pattern or a front-facing one goes there, so that
    turns land where official charts put them and the chart's share of turns follows the official one for its level."""
    def __init__(self,events,level,seed):
        self.b=turn_band(level);self.seed=seed;self.seen=0;self.placed=0.
        ms=[e['ms'] for e in events];import bisect
        win=[bisect.bisect_right(ms,t+1000)-bisect.bisect_left(ms,t-1000) for t in ms]
        hot=sorted(win)[int(.8*(len(win)-1))] if win else 1
        self.inten=[min(2.,w/max(1,hot)) for w in win];self.events=events
    def want_turn(self,i,n,salt):
        evs=self.events[i:i+n]
        if len(evs)<2:return False
        gaps=sorted(b['beat']-a['beat'] for a,b in zip(evs,evs[1:]));g=gaps[len(gaps)//2]
        rh='16th' if abs(g-.25)<.02 else '8th' if abs(g-.5)<.02 else 'trip' if abs(g-1/3)<.02 else 'quarter' if abs(g-1)<.02 else 'other'
        inten=sum(self.inten[i:i+n])/len(evs)
        w=TURN_INTENSITY[self.b][min(4,int(inten*4))]*TURN_RHYTHM[rh][self.b]
        if i==0 or self.events[i]['beat']-self.events[i-1]['beat']>=1-1e-6:w*=TURN_RUN_START[self.b]
        target=TURN_TARGET[self.b];fb=min(2.,max(.5,(target*self.seen+1)/(self.placed+1)))
        p=min(1.,target*w*fb/.45)   # .45 = turns per step of the turning user patterns
        raw=hashlib.blake2s(repr((self.seed,'turn',salt)).encode(),digest_size=4).digest()
        return int.from_bytes(raw,'little')/2**32<p
    def account(self,steps,turns):self.seen+=steps;self.placed+=turns

def row_hints(events,level,seed,blocked=frozenset(),budget=None,flipped=frozenset()):
    """Places user row patterns where the original has the same shape: notes per row, hold count, holds ending on the
    pattern's row, onsets on the pattern's rows (one row = an 8th or slower). The last step is shared with the next
    pattern. v3: the budget picks a turning or a front-facing pattern for each spot. Returns {event index: lanes
    (hold lanes first)}, the ids used and each placement's event indices (flipped: placements to mirror the other way)."""
    pats=[p for p in user_row_patterns() if allowed(p[1],level)];hints={};used=Counter();log=[];i=0;arrival=None;segs=[];feet={}
    budget=budget or TurnBudget(events,level,seed)
    while pats and i<len(events):
        found=[]
        for pid,_,steps in pats:
            win=events[i:i+len(steps)]
            if len(win)<len(steps) or any(e['index'] in blocked for e in events[i:i+len(steps)+8]):continue
            unit=(win[1]['beat']-win[0]['beat'])/(steps[1][0]-steps[0][0])
            if unit<.5-1e-3:continue
            at=lambda r:win[0]['beat']+unit*(r-steps[0][0])
            if all(len(e['lanes'])==len(s[1]) and len(e['holds'])==len(s[2]) and abs(e['beat']-at(s[0]))<1e-3
                   and sorted(round(b,3) for b in e['hold_ends_beat'].values())==sorted(round(at(x),3) for x in s[2].values())
                   for e,s in zip(win,steps)):
                found+=[(pid,steps,flip) for flip in (False,True)]
        # right after a pattern its arrival note is shared: the next one must start with exactly those panels
        if arrival is not None:found=[f for f in found if (tuple(4-l for l in f[1][0][1]) if f[2] else f[1][0][1])==arrival]
        if found:
            turn=budget.want_turn(i,len(found[0][1]),('rows',i))
            found=[f for f in found if (pattern_meta(f[0])['turns']>0)==turn]
        if not found:i+=1;arrival=None;continue
        raw=hashlib.blake2s(repr((seed,'rows',i)).encode(),digest_size=4).digest()
        short=[f for f in found if pattern_meta(f[0])['max_cross_run']<=1]
        if short and raw[1]/256<ONE_STEP_SHARE:found=short
        low=min(used[f[0]] for f in found);found=[f for f in found if used[f[0]]==low]
        side=bool(raw[0]&1)!=(events[i]['index'] in flipped);found=[f for f in found if f[2]==side] or found
        pid,steps,flip=found[int.from_bytes(raw,'little')%len(found)];used[pid]+=1
        pf=pattern_meta(pid)['feet'] or [2]*len(steps)
        for e,s,f in zip(events[i:],steps,pf):hints[e['index']]=tuple(4-l for l in s[1]) if flip else s[1];feet[e['index']]=1-f if flip and f<2 else f
        segs.append([e['index'] for e in events[i:i+len(steps)]])
        m=pattern_meta(pid);budget.account(len(steps)-1,m['turns'])
        arrival=hints[events[i+len(steps)-1]['index']];log.append(pid+('m' if flip else ''));i+=len(steps)-1
    return hints,log,segs,feet

class UserChain:
    """Walks user patterns note by note. When one ends, the next starts on the panel where it ended (that note is
    shared) AND with the foot that stepped it (v3.1: a pattern is played with a given parity; chaining one that starts
    on the other foot forces the composer off the pattern), so every junction is itself a validated move. Each pattern
    may be mirrored on its own (a mirror swaps the feet). v3: turning or front-facing as the turn budget says.
    invert: a fresh chain (segment) starts mirrored the other way (the composer could not follow it as drawn)."""
    def __init__(self,seed,level=20):
        self.seed=seed;self.level=level;self.seq=None;self.pos=0;self.flip=False;self.used=Counter();self.log=[];self.turns=0
        self.invert=False;self.since_twist=TWIST_GAP
    def _pick(self,first,salt,turn):
        pats=[u for u in user_patterns() if allowed(pattern_meta(u[0]),self.level)]
        kind=lambda u:turn is None or (pattern_meta(u[0])['turns']>0)==turn
        raw=hashlib.blake2s(repr((self.seed,'user',salt)).encode(),digest_size=4).digest()
        options=[(u,g) for u in pats for g in (False,True) if kind(u)]
        if first is not None:   # first = (panel, foot) of the shared note, as played
            lane,foot=first
            fits=lambda u,g:(4-u[1][0] if g else u[1][0])==lane and (foot is None or pattern_meta(u[0])['start_foot'] in (None,foot if not g else 1-foot))
            chained=[o for o in options if fits(*o)] or [(u,g) for u in pats for g in (False,True) if fits(u,g)]
            if chained:options=chained
            else:first=None   # nothing starts here with that foot: start a new chain
        if first is None:
            g0=bool(raw[0]&1)!=self.invert;options=[o for o in options if o[1]==g0] or [(u,g0) for u in pats]
        twists=[o for o in options if pattern_meta(o[0][0])['twist']]
        if turn and self.since_twist>=TWIST_GAP and twists and raw[2]/256<TWIST_SHARE:options=twists
        else:
            if self.since_twist<TWIST_GAP or not turn:options=[o for o in options if not pattern_meta(o[0][0])['twist']] or options
            short=[o for o in options if pattern_meta(o[0][0])['max_cross_run']<=1]
            if short and raw[1]/256<ONE_STEP_SHARE:options=short
        low=min(self.used[o[0][0]] for o in options);pool=[o for o in options if self.used[o[0][0]]==low]
        (pid,seq),g=pool[int.from_bytes(raw,'little')%len(pool)];self.used[pid]+=1;self.turns+=pattern_meta(pid)['turns']
        self.seq,self.flip=seq,g;self.pos=0 if first is None else 1
        if pattern_meta(pid)['twist']:self.since_twist=0
        self.log.append(pid+('m' if g else ''))
    def end(self):
        m=pattern_meta(self.log[-1].rstrip('m'));f=m.get('end_foot')
        return (4-self.seq[-1] if self.flip else self.seq[-1]),(None if f is None else 1-f if self.flip else f)
    def take(self,n,salt,turn=None):
        out=[]
        while len(out)<n:
            if self.seq is None:self._pick(None,(salt,len(out)),turn)
            elif self.pos>=len(self.seq):self._pick(self.end(),(salt,len(out)),turn)
            f=(pattern_meta(self.log[-1].rstrip('m'))['feet'] or [2]*len(self.seq))[self.pos]
            out.append((4-self.seq[self.pos] if self.flip else self.seq[self.pos],1-f if self.flip and f<2 else f));self.pos+=1;self.since_twist+=1
        return out
    def reset(self):self.seq=None

def skill_of(lanes,gaps):
    if any(a==b for a,b in zip(lanes,lanes[1:])):return 'jack'
    for i in range(len(lanes)-4):
        w=lanes[i:i+5]
        if w[0]==w[2]==w[4] and w[1]==w[3] and w[0]!=w[1]:return 'drill'
    for i in range(len(lanes)-4):
        if len(set(lanes[i:i+5]))==5:return 'staircase'
    if len(set(lanes[::2]))==1 or len(set(lanes[1::2]))==1:return 'anchor_run'
    if all(g<=.5+1e-6 for g in gaps) and len(set(lanes))>=3:return 'run'
    return 'flow'

def _bank():
    global _BANKS
    if _BANKS is None:
        here=Path(__file__).parent;p=here/'official_skill_motifs.json'
        _BANKS=('official',json.loads(p.read_text('utf8'))) if p.exists() else ('native',json.loads((here/'native_phrase_motifs.json').read_text('utf8')))
    return _BANKS

def _index(key,pool):
    if key not in _INDEX:
        sig={}
        for m in pool:sig.setdefault(tuple(round(g,3) for g in m['gaps']),[]).append(m)
        _INDEX[key]=sig
    return _INDEX[key]

def preferences(events,columns,level,seed,user=True):
    key=(tuple((e['index'],e['beat']) for e in events),columns,level,seed,user)
    if key in _MEMO:return _MEMO[key]
    _MEMO.clear();_MEMO[key]=r=_preferences(events,columns,level,seed,user);return r

def _preferences(events,columns,level,seed,user=True):
    kind,banks=_bank()
    keys=[k for k in banks if k.startswith(str(columns)+'_')]
    if not keys:return {},{'native_vocabulary_available':False,'blocks':0}
    key=min(keys,key=lambda k:abs(int(k.split('_')[1])-level))
    pool=[m for m in banks[key] if len(m['lanes'])==8 and len(m['gaps'])==7]
    sig=_index(key,pool);frequent=pool[:3000]
    hints={};used=Counter();blocks=0;mirrors=0;exact=0;matched=0;last_skill=None;skills=Counter()
    active=bool(user) and columns==5 and level>=USER_MIN_LEVEL and VARIANT!='E'
    chain=UserChain(seed,level) if active and user_patterns() and VARIANT!='F' else None;user_ix=[];user_blocks=0
    budget=TurnBudget(events,level,seed) if active else None
    # user may be (blocked, flipped): event indices where user patterns boxed the route in or were not followed (that
    # block and the one before get none), and first notes of segments to mirror the other way
    blocked,flipped=user if isinstance(user,tuple) else (frozenset(),frozenset())
    # Row patterns (jumps/holds) where the original has their exact shape; nothing else overwrites them.
    rows,row_log,segments,feet=(twist_hints if VARIANT=='F' else row_hints)(*((events,level,seed,blocked,flipped) if VARIANT=='F' else (events,level,seed,blocked,budget,flipped))) if active else ({},[],[],{})
    hints.update(rows);user_ix+=list(rows)
    for start in range(0,len(events),8):
        chunk=events[start:start+8]
        if len(chunk)<8:break
        gaps=[max(.00001,b['beat']-a['beat']) for a,b in zip(chunk,chunk[1:])]
        src=[e['lanes'][0] if len(e['lanes'])==1 else None for e in chunk]
        # User patterns first, any rhythm, on blocks of single taps whose original is not a jack/drill (those keep
        # their repeated panels). Consecutive user blocks continue the same chain.
        if (chain and None not in src and not any(e['holds'] for e in chunk) and skill_of(src,gaps) not in ('jack','drill')
                and not any(e['index'] in blocked for e in events[start:start+16]) and not any(e['index'] in rows for e in chunk)):
            before=chain.turns;turn=budget.want_turn(start,8,('seq',start))
            if chain.seq is None:chain.invert=chunk[0]['index'] in flipped;segments.append([])
            for e,(l,f) in zip(chunk,chain.take(8,start,turn)):hints[e['index']]=l;feet[e['index']]=f;user_ix.append(e['index']);segments[-1].append(e['index'])
            budget.account(8,chain.turns-before)
            blocks+=1;user_blocks+=1;skills['user']+=1;last_skill='user'
            continue
        if chain:chain.reset()
        want=skill_of(src,gaps) if None not in src else None
        if VARIANT in 'DEF' and want not in ('jack','drill'):blocks+=1;skills['vortex']+=1;last_skill='vortex';continue   # filled below
        cands=sig.get(tuple(round(g,3) for g in gaps))
        if cands:
            exact+=1;same=[m for m in cands if want in STRONG and m.get('skill')==want][:40]
            scored=[(0.,m) for m in same+[m for m in cands[:60] if m not in same]]
        else:
            if len(_SIM)>4000:_SIM.clear()
            sims=_SIM.get((key,tuple(gaps)))
            if sims is None:
                sims=_SIM[(key,tuple(gaps))]=sorted(((sum(abs(math.log((a+.05)/(float(b)+.05))) for a,b in zip(gaps,m['gaps']))/7,i) for i,m in enumerate(frequent)))[:60]
            scored=[(s,frequent[i]) for s,i in sims]
            if want in STRONG:   # also offer the closest same-skill motifs of the whole band
                skey=(key,'skill',want)
                if skey not in _SIM:_SIM[skey]=[m for m in pool if m.get('skill')==want][:3000]
                near_skill=sorted(((sum(abs(math.log((a+.05)/(float(b)+.05))) for a,b in zip(gaps,m['gaps']))/7,m) for m in _SIM[skey]),key=lambda x:x[0])[:20]
                scored+=near_skill
        rank=[]
        for s,m in scored:
            ms=m.get('skill','flow');ident=tuple(m['lanes'])
            cost=s+.20*used[ident]
            if want in STRONG:cost+=0. if ms==want else .45          # follow the original's own skill
            elif ms==last_skill:cost+=.15                             # otherwise vary skills phrase to phrase
            rank.append((cost,ident,ms))
        rank.sort(key=lambda x:(x[0],x[1]));near=rank[:8]
        raw=hashlib.blake2s(repr((seed,tuple(round(g,5) for g in gaps),start//8)).encode(),digest_size=4).digest()
        _,lanes,ms=near[int.from_bytes(raw,'little')%len(near)]
        used[lanes]+=1;skills[ms]+=1;last_skill=ms;matched+=want is not None and ms==want
        if raw[0]&1:
            mirror=(4,3,2,1,0) if columns==5 else (9,8,7,6,5,4,3,2,1,0)
            lanes=tuple(mirror[l] for l in lanes);mirrors+=1
        for e,l in zip(chunk,lanes):
            if e['index'] not in rows:hints[e['index']]=l
        blocks+=1
    vx_log=[];vd={}
    if VARIANT in 'DEF' and columns==5:   # ArrowVortex walk on every single tap nothing above holds (the composer picks)
        vd,vx_log=vortex.draws(events,level,seed,set(hints))
    return hints,{'native_vocabulary_available':True,'bank':kind,'reference_band':key,'blocks':blocks,'exact_rhythm_matches':exact,
        'skill_matches_original':matched,'skills_used':dict(skills),'distinct_motifs':len(used),'mirrored_blocks':mirrors,
        'user_pattern_blocks':user_blocks,'user_patterns_used':chain.log if chain else [],'user_row_patterns_used':row_log,'user_indices':user_ix,
        'user_segments':segments,'user_feet':feet,'vortex_sections':vx_log,'vortex_draws':vd,
        'method':'user-validated row patterns where the original has their shape, then user panel sequences (Single level 13+, any rhythm, not on jacks/drills), then official PIU 8-onset motifs, exact rhythm match first, original-skill preference, variety penalty; soft only'}
