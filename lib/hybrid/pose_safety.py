"""Front-facing conservative *stance-proxy* guard for two-foot PIU planning.

Angle is inferred from the line joining contact points; it is NOT torso yaw.
Rules reject rapid swaps between opposing diagonals and repeated oscillations.
No brackets, in-air feet, torso kinematics or choreographed 180-degree spins.
"""
from __future__ import annotations
import math

POLICIES={
    'strict': {'direct_min_ms':1050.,'window_ms':1550.,'budget_deg':170.},
    'guarded':{'direct_min_ms':450.,'window_ms':850.,'budget_deg':230.},
    'balanced':{'direct_min_ms':0.,'window_ms':650.,'budget_deg':300.},
    # v363: costs only. Front-facing +-45 stream wiggles are normal Pump footwork;
    # physical safety is enforced by the natural-reading gate (playability.py).
    'soft':{'direct_min_ms':0.,'window_ms':650.,'budget_deg':1e9},
    'off':{'direct_min_ms':0.,'window_ms':0.,'budget_deg':1e9},
}


def stance_yaw(positions, coords):
    left,right=(coords[k] for k in positions)
    return math.degrees(math.atan2(-(right[1]-left[1]),right[0]-left[0]))


def evolve(trace, old_yaw, new_yaw, now, previous_ms, policy='balanced'):
    """Return (new_trace, penalty, rejection_code_or_None).

    trace entries are (time_ms, magnitude_of_stance_angle_change).
    Only Single strict mode uses the extra anti-spin barriers by default.
    """
    delta=abs(new_yaw-old_yaw)
    if policy not in POLICIES:raise ValueError('unknown anti-spin policy '+str(policy))
    if policy=='off':return tuple(trace), .0, None
    rule=POLICIES[policy]
    if abs(new_yaw)>60.+1e-7:
        return tuple(trace),0.,'BACK_OR_SIDE_FACING_PROXY'
    # Crossing the center axis directly makes a 90-degree reversal, often
    # misread as a playable twist even though there is no neutral setup.
    if old_yaw*new_yaw< -1e-5 and min(abs(old_yaw),abs(new_yaw))>=20.:
        if now-previous_ms<rule['direct_min_ms']-1e-7:
            return tuple(trace),0.,'DIAGONAL_REVERSAL_NO_RECOVERY'
    retained=tuple((t,d) for t,d in trace if now-t<rule['window_ms']-1e-7)
    accumulated=sum(d for _,d in retained)+delta
    if accumulated>rule['budget_deg']+1e-7:
        return retained,0.,'ANGULAR_OSCILLATION_WINDOW'
    newtrace=retained+(((now,delta),) if delta>=1.e-5 else ())
    # Explicit small energetic cost for changing the stance estimate.
    # Avoids exploiting diagonal-flip transitions just to please a lane prior.
    reversal=old_yaw*new_yaw< -1e-5
    extra= (4.0 if reversal and now-previous_ms<=450. else 1.25 if reversal else 0.)
    return newtrace, .20*(delta/45.)**2+.10*(accumulated/90.)**2+extra, None


def audit_pose_path(plan, clock, coords, initial=(0,4), policy='balanced'):
    pos=list(initial);old_yaw=stance_yaw(pos,coords);previous_ms=clock[plan[0]['index']][1]-2000. if plan else 0.
    trace=();flags=[];stats={'opposing_diagonal_reversals':0,'hard_guard_violations':0,
                              'max_recent_turn_degrees':0.,'maximum_proxy_abs_degrees':abs(old_yaw)}
    for item in plan:
        newpos=pos[:]
        for lane,foot,_ in item['actions']:newpos[foot]=lane
        now=clock[item['index']][1]
        yaw=stance_yaw(newpos,coords)
        if old_yaw*yaw < -1.e-5:stats['opposing_diagonal_reversals']+=1
        nexttrace,_,reason=evolve(trace,old_yaw,yaw,now,previous_ms,policy)
        if reason:
            stats['hard_guard_violations']+=1
            flags.append({'index':item['index'],'beat':clock[item['index']][0],
                          'reason':reason,'previous_yaw':old_yaw,'new_yaw':yaw,
                          'delta_ms':now-previous_ms})
        trace=nexttrace
        stats['max_recent_turn_degrees']=max(stats['max_recent_turn_degrees'],sum(d for _,d in trace))
        stats['maximum_proxy_abs_degrees']=max(stats['maximum_proxy_abs_degrees'],abs(yaw))
        pos=newpos;old_yaw=yaw;previous_ms=now
    return stats,flags
