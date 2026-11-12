#!/usr/bin/env python3
"""Portable, reproducible single-file chart generation. Never installs a chart."""
from pathlib import Path
import json, argparse, time, hashlib, sys
from hybrid.sources import respect,events_of,render,ssc_text,sha
from hybrid.composer import compose,NoRoute
from hybrid.validation import validate
from hybrid.skill_validation import observe
from hybrid import nx20,__version__

def write_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.new');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(path)

def travel(columns,level):
    x=json.loads((Path(__file__).parent/'hybrid/native_travel_calibration.json').read_text())
    key=f'{columns}_{min(26,(level-1)//5*5+1)}';band=x['bands'].get(key)
    base=5+level*.10
    if band and band['compatible_phrases']>=20:return max(base,band['speed_p90']),key
    return base,'original-low-density-bound'

def generate(input_file,out,keys,columns,level,tier,beam,seed,title,artist,music='audio.ogg',
             pose_policy='guarded',skill_weight=4.0,recovery_policy='strict'):
    out=Path(out)
    if out.exists() and any(out.iterdir()):raise FileExistsError(f'Output exists; use a new folder: {out}')
    out.mkdir(parents=True,exist_ok=True);start=time.time()
    source,audit=respect(input_file,keys);tl,events=events_of(source);speed,band=travel(columns,level)
    result=compose(events,columns,level,tier,beam,seed,speed,pose_policy=pose_policy,skill_weight=skill_weight,
                   recovery_policy=recovery_policy)
    nx=render(source,result['plan'],columns,level)
    verification=validate(source,nx,result['plan'],tl,events,columns,level,tier,result['ledger'],speed,pose_policy=pose_policy,recovery_policy=recovery_policy)
    if not verification['pass']:
        write_json(out/'REJECTED.json',{'verification':verification,'source':audit})
        raise ValueError('independent validator rejected: '+str(verification['errors'][:8]))
    raw=nx20.build(nx);receipt={'version':__version__,'title':title,'artist':artist,'mode':'Single' if columns==5 else 'Double',
        'level_provisional':level,'tier':tier,'source':audit,'metrics':result['metrics'],'verification':verification,
        'native_travel_band':band,'sha256':hashlib.sha256(raw).hexdigest(),'installed':False,
        'native_engine_tested':False,'human_playtest_pending':True,'seconds':round(time.time()-start,3)}
    (out/'chart.nx').write_bytes(raw)
    (out/'chart.ssc').write_text(ssc_text(source,[(level,tier,nx)],title,artist,music),encoding='utf8')
    write_json(out/'receipt.json',receipt);write_json(out/'foot_plan.json',result['plan'])
    write_json(out/'delta_ledger.json',result['ledger']);write_json(out/'phrases.json',result['phrases'])
    write_json(out/'source_events.json',events)
    write_json(out/'skills_and_posture_review.json',{
        'source_skill_intents':result['metrics']['skills'],
        'posture':verification['footmetrics'],
        'twist_recovery':verification.get('recovery',{}),
        'execution':observe(events,result['plan']),
        'warning':'Stance angle is not torso yaw. Direct inversions require human review even when validation passes.',
        'pose_policy':pose_policy,'human_playtest_pending':True})
    return receipt

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',required=True,type=Path,help='original RESPECT TextAsset .bytes')
    p.add_argument('--out',required=True,type=Path);p.add_argument('--keys',required=True,type=int,choices=(4,5,6,8))
    p.add_argument('--columns',type=int,choices=(5,10),default=5);p.add_argument('--level',type=int,default=20)
    p.add_argument('--tier',choices=('EASY','MEDIUM','HARD'),default='HARD');p.add_argument('--beam',type=int,default=64)
    p.add_argument('--seed',type=int,default=36);p.add_argument('--title',required=True);p.add_argument('--artist',default='')
    p.add_argument('--pose-policy',choices=('strict','guarded','balanced','off'),default='guarded',
                   help='strict: fail closed on quick opposite-diagonal moves; balanced: reject oscillations and flag flips; off: legacy audit')
    p.add_argument('--skill-weight',type=float,default=4.,help='0..5, source-key skill intent weight')
    p.add_argument('--recovery-policy',choices=('strict','off'),default='strict')
    p.add_argument('--music',default='audio.ogg');a=p.parse_args()
    try:
        r=generate(a.input,a.out,a.keys,a.columns,a.level,a.tier,a.beam,a.seed,a.title,a.artist,a.music,a.pose_policy,a.skill_weight,a.recovery_policy)
        print(json.dumps({'pass':True,'output':str(a.out.resolve()),'sha256':r['sha256'],'verification':r['verification']['pass']}))
    except (ValueError,FileExistsError) as ex:print(str(ex),file=sys.stderr);return 2
    return 0

if __name__=='__main__':raise SystemExit(main())
