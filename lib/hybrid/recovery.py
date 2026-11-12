"""Conservative, source-timed Pump Single twist recovery contracts.

These templates are *contact-sequence hypotheses* derived from the user's
UR-CE-UR / UL-CE-UL examples. The output never adds a timestamp: exits must
use the NEXT selected BMS attack(s). No torso direction is certified by this
contact-only model. Pairs use the same two-head source attack, not an invented
extra note. A bracket means two taps at one instant made with one foot, with
no continuing hold, and has a separate physical eligibility check.
"""
from __future__ import annotations
from dataclasses import dataclass

DL,UL,CE,UR,DR=0,1,2,3,4
SIDE_CORES={UR: (UR,CE,UR),UL: (UL,CE,UL)}
MAX_EXIT_BEATS=3.0
MAX_EXIT_MS=1700.0

@dataclass(frozen=True,slots=True)
class Pending:
    side:int
    phase:str  # NEXT or EXPECT_OPPOSITE
    opened_beat:float
    opened_ms:float
    core_foot:int


def valid_bracket(actions, *, level=20, holds=()):
    """Only isolated heel/toe contact geometry tested here (not certification).

    One foot, two simultaneous TAP heads. Right may CE+DR, left CE+DL.
    Consecutive holds, multi-foot brackets and other pairs are not modeled.
    """
    if level<17 or holds or len(actions)!=2 or any(a[2]>=0 for a in actions):
        return False
    panels={a[0] for a in actions};feet={a[1] for a in actions}
    return (panels=={CE,DR} and feet=={1}) or (panels=={CE,DL} and feet=={0})


def _is_core(recent, actions, beat, ms):
    if len(actions)!=1 or len(recent)<2:return None
    (a,fa,ba,ma),(b,fb,bb,mb)=recent[-2:]
    c,fc,_=actions[0]
    if any(x<=0 or x>1.0 for x in (bb-ba,beat-bb)):
        return None
    if ma>=mb or mb>=ms or ms-ma>1800.:return None
    if (a,b,c) not in SIDE_CORES.values():return None
    # The two matching corner attacks reuse the same foot, separated by CE.
    if fa!=fc or fa==fb:return None
    return c,fc


def step(pending, recent, actions, beat, ms, *, level=20, enabled=True):
    """Evaluate ONE available BMS attack. Return pending, event_label, reason.

    The existing foot-travel/hold/stance constraints are checked separately.
    An exit label never overrides a physical failure or declares a true torso
    orientation. If no valid exit is present, the candidate is rejected.
    """
    actions=tuple(tuple(a) for a in actions)
    if not enabled:
        return None,'DISABLED',None
    if pending is not None:
        if (beat-pending.opened_beat>MAX_EXIT_BEATS+1e-7 or
            ms-pending.opened_ms>MAX_EXIT_MS+1e-7):
            return pending,'', 'RECOVERY_DEADLINE'
        side=pending.side
        opposite=UL if side==UR else UR
        panels=tuple(a[0] for a in actions)
        pair=frozenset(panels)
        if pending.phase=='EXPECT_OPPOSITE':
            if len(actions)==1 and panels[0]==opposite:
                return None,'FRONT_CE_OPPOSITE',None
            return pending,'','RECOVERY_EXPECTED_OPPOSITE'
        if len(actions)==1:
            if panels[0]==CE:
                return Pending(side,'EXPECT_OPPOSITE',pending.opened_beat,pending.opened_ms,
                               pending.core_foot),'CE_SETUP',None
            if panels[0]==side:
                # Additional same-corner attack is one user's recovery choice.
                # No fixed foot claim: collision/availability checked elsewhere.
                return None,'FRONT_REATTACK_CORNER',None
            return pending,'','RECOVERY_NO_ALLOWED_SINGLE_EXIT'
        if len(actions)==2:
            if pair=={DL,DR} and len({a[1] for a in actions})==2:
                return None,'FRONT_LOW_JUMP',None
            sidepair={side,DR if side==UR else DL}
            if pair==sidepair and len({a[1] for a in actions})==2:
                return None,'SIDE_CONTINUATION_JUMP',None
            bracket={CE,DR if side==UR else DL}
            if pair==bracket and valid_bracket(actions,level=level):
                return None,'BRACKET_FREE_OTHER_FOOT',None
            return pending,'','RECOVERY_NO_ALLOWED_PAIR_EXIT'
        return pending,'','RECOVERY_UNSUPPORTED_CARDINALITY'
    # Only treat a matching 3-tap contact motif as a committed core if it is
    # realized with alternating feet. Keyboard A-B-A is NOT a twist by itself.
    core=_is_core(recent,actions,beat,ms)
    if core:
        if level<12:
            return None,'','LOW_LEVEL_TWIST_CORE_BLOCKED'
        side,core_foot=core
        return Pending(side,'NEXT',beat,ms,core_foot),'TWIST_CORE_COMMITTED',None
    return None,'NORMAL',None


def append_history(recent, actions, beat, ms):
    if len(actions)==1:
        lane,foot,_=actions[0]
        return (recent+((lane,foot,float(beat),float(ms)),))[-3:]
    return ()  # chords interrupt a 3-single motif


def replay(plan, clock, *, level=20):
    """Independent linear recovery contract replay over generated foot actions.

    Does not infer physical human facing; only checks the contractual note
    exits and their deadlines. A corrupted or incomplete plan must fail.
    """
    state=None;recent=();errors=[];decisions=[]
    for item in plan:
        i=item['index'];beat,ms=clock[i][:2]
        actions=tuple(tuple(a) for a in item['actions'])
        state,event,err=step(state,recent,actions,beat,ms,level=level)
        if err:errors.append({'index':i,'beat':beat,'reason':err})
        if event!='NORMAL':decisions.append({'index':i,'beat':beat,'event':event})
        recent=append_history(recent,actions,beat,ms)
    if state is not None:
        errors.append({'index':plan[-1]['index'],'reason':'UNCLOSED_TWIST_RECOVERY',
                       'open_beat':state.opened_beat,'phase':state.phase})
    return {'valid':not errors,'errors':errors,'decisions':decisions,
            'cores':sum(x['event']=='TWIST_CORE_COMMITTED' for x in decisions),
            'closed':sum(x['event'].startswith(('FRONT_','SIDE_','BRACKET_')) for x in decisions)}
