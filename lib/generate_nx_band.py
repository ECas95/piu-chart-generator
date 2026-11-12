"""Generate one requested band from a bound native reference, with independent grading.

Original NX files are never modified. Added rhythmic subdivisions and removed
easy-tier onsets have separate complete ledgers. Out-of-band results stay offline.
"""
from pathlib import Path
import sys,json,math,copy,inspect,collections,bisect,time,hashlib,argparse,shutil,ast
R=Path(__file__).resolve().parent;B=R.parent
ALGO=R
sys.path[:0]=[str(R),str(R/'engine')]
from hybrid import composer,sources,nx20
from hybrid.validation import validate
from rhythm_extension import extend
from generate import travel
from beginner_grading import certify,certify_single
from easy_hold_policy import simplify,density_hold_keys,concurrency_hold_keys
import playability
spec=__import__('importlib.util',fromlist=['spec_from_file_location']).spec_from_file_location('frozen_native_level_model',R/'engine/difficulty_model.py')
MODEL=__import__('importlib.util',fromlist=['module_from_spec']).module_from_spec(spec);spec.loader.exec_module(MODEL)
BANDS=[(1,5),(6,12),(13,17),(18,20)]
DENSITY={'Single':[1.1,3.0,6.2,6.9],'Double':[1.1,2.7,5.3,6.3]}  # v363 starting points from calibrated samples
TARGETS=[3,9,15,19]

def metrics(events,phase_origin=0.):
    times=[e['ms'] for e in events];span=max(1.,(times[-1]-times[0])/1000);heads=sum(len(e['lanes']) for e in events)
    def peak(seconds):
        left=0;highest=0
        for right,at in enumerate(times):
            while at-times[left]>seconds*1000:left+=1
            highest=max(highest,right-left+1)
        return highest/seconds
    return dict(row_nps=len(times)/span,note_nps=heads/span,peak_row_1s=peak(1),peak_row_4s=peak(4),peak_row_8s=peak(8),jump_rows=sum(len(e['lanes'])>1 for e in events)/len(events),hold_heads=sum(len(e['holds']) for e in events)/max(heads,1),offbeat_rows=sum(abs((e['beat']-phase_origin)-round(e['beat']-phase_origin))>1e-5 for e in events)/len(events),sixteenth_rows=sum(abs((e['beat']-phase_origin)*2-round((e['beat']-phase_origin)*2))>1e-5 for e in events)/len(events))

def selector(target_nps,phase_origin=0.,beginner_only=False,exclude=frozenset()):
    def select(events,tier):
        # v363: onsets excluded after a physical conflict (NoRoute/natural-reading
        # gate) are omitted with an individual ledger entry; never hold heads.
        dropped=[dict(kind='OMIT_ONSET',index=e['index'],beat=e['beat'],source_lanes=e['lanes'],reason='v363 physical conflict at this onset (NoRoute or natural-reading gate)',tier=tier) for e in events if e['index'] in exclude]
        events=[e for e in events if e['index'] not in exclude]
        if tier=='HARD':return list(events),dropped
        chosen={e['index'] for e in events if e['holds']};groups=collections.defaultdict(list)
        held=[(e['ms'],e['hold_ends_ms'][end]) for e in events for end,_ in e['holds']]
        for e in events:groups[int((e['beat']-phase_origin)//8)].append(e)
        for q,es in groups.items():
            span=max(.5,(es[-1]['ms']-es[0]['ms'])/1000)
            budget=max(1,round(target_nps*span));mandatory=sum(e['index'] in chosen for e in es)
            ordered=sorted(es,key=lambda e:(0 if abs((e['beat']-phase_origin)-round(e['beat']-phase_origin))<1e-5 else 1 if abs((e['beat']-phase_origin)*2-round((e['beat']-phase_origin)*2))<1e-5 else 2,e['ms']))
            added=0;kept_times=sorted(e['ms'] for e in es if e['index'] in chosen)
            for e in ordered:
                if e['index'] in chosen:continue
                if beginner_only and abs((e['beat']-phase_origin)-round(e['beat']-phase_origin))>1e-5:continue
                # Lower tiers may omit a tap onset, with a ledger entry; they
                # must never cancel a hold to manufacture a third free contact.
                if sum(start<e['ms']-1e-5 and e['ms']<end-1e-5 for start,end in held)>=2:continue
                if added>=max(0,budget-mandatory):break
                p=bisect.bisect_left(kept_times,e['ms']);floor=min(300.,650/target_nps)
                if (p and e['ms']-kept_times[p-1]<floor) or (p<len(kept_times) and kept_times[p]-e['ms']<floor):continue
                chosen.add(e['index']);bisect.insort(kept_times,e['ms']);added+=1
        if not chosen:
            if beginner_only:return selector(target_nps,phase_origin,False,exclude)(events,tier)  # v363: no on-beat attacks -> regular easy selection
            chosen.add(events[0]['index'])
        return [e for e in events if e['index'] in chosen],[dict(kind='OMIT_ONSET',index=e['index'],beat=e['beat'],source_lanes=e['lanes'],reason='whole-phrase rhythmic subdivision',tier=tier) for e in events if e['index'] not in chosen]+dropped
    return select

class HoldConflict(Exception):
    def __init__(self,event):self.event=event

def generate(reference,band,out,*,seed=362,beam=64,target_density=None,planner_level=None,avoid_added_windows=(),simplify_hold_keys=(),simplify_excess_easy_holds=False,generation_only=False):
    start=time.time();out=Path(out)
    # v363 speed: optional per-job budget (env PIU_TIME_BUDGET seconds); TIME_BUDGET jobs get a final unbudgeted pass
    budget=float(__import__('os').environ.get('PIU_TIME_BUDGET') or 0)
    def check_budget():
        if budget and time.time()-start>budget:raise ValueError(f'TIME_BUDGET {budget:.0f}s exceeded; retried later without budget')
    if out.exists() and any(out.iterdir()):raise FileExistsError('Preserve prior generation run: '+str(out))
    out.mkdir(parents=True,exist_ok=True);ref=json.loads(Path(reference).read_text(encoding='utf8'))
    if ref.get('audio_clock_binding_review_required') or ref.get('final_generation_ready') is False:
        raise ValueError('Reference is internal research only until active-media audio clock binding is independently verified')
    if ref.get('audio_clock_binding'):
        binding=Path(ref['audio_clock_binding']).read_bytes()
        assert hashlib.sha256(binding).hexdigest()==ref['audio_clock_binding_sha256'],'Audio binding receipt changed'
        assert json.loads(binding)['pass_'],'Audio clock binding did not pass'
    if ref.get('original_harder_than_current_reference'):raise ValueError('Hardest original reference has not been bound; do not silently use the easier installed chart')
    raw=Path(ref['file']).read_bytes();assert hashlib.sha256(raw).hexdigest()==ref['sha256'];source=nx20.parse(raw)
    cols=5 if ref['mode']=='Single' else 10;assert 1<=source['cols']<=18
    density=target_density if target_density is not None else DENSITY[ref['mode']][band-1]
    if simplify_excess_easy_holds:
        simplify_hold_keys=sorted(set(map(tuple,simplify_hold_keys))|set(density_hold_keys(source,band=band,target_density=density)))
    pristine=source;structural=concurrency_hold_keys(source);conflict_holds=[]
    def resimplify():
        keys=set(structural)|set(conflict_holds)
        src,ledger=simplify(pristine,sorted(set(map(tuple,simplify_hold_keys))|keys),band=band,verify=not generation_only,structural=sorted(keys))
        for entry in ledger:
            k=(entry['source_index'],entry['source_lane'])
            entry['selection_policy']=('v363 user-authorized: hold with no free foot (route conflict) -> tap in new variant' if k in conflict_holds else
                'v363: third simultaneous hold -> tap (two feet)' if k in structural else 'EASY phrase-density hold budget')
        return src,ledger
    source,hold_ledger=resimplify()
    (out/'whole_hold_simplification_ledger.json').write_text(json.dumps(hold_ledger,indent=2),encoding='utf8')
    low,high=BANDS[band-1];density=target_density if target_density is not None else DENSITY[ref['mode']][band-1]
    def attempt(density):
        expanded,additions,augmentation=extend(source,density,seed=seed,avoid_added_windows=avoid_added_windows,verify=not generation_only)
        tl,events=sources.events_of(expanded);tier='EASY' if band<=2 else 'MEDIUM' if band==3 or (ref['chart']['level']>20 and not ref.get('source_is_original_ddr')) else 'HARD'
        if tier_override:tier=tier_override[0]  # v363: HARD kept every onset but could not fit the band/route
        # Bind the requested phrase-density selector to a local copy of the final
        # algorithm. Its contact, hold, turn and recovery checks are unchanged.
        exclude=set();env=dict(composer.__dict__);env['select']=selector(density,tl[0][0],beginner_only=band==1,exclude=exclude);env['beginner_contacts']=(band==1)
        tree=ast.parse(inspect.getsource(composer.compose))
        class BeginnerCaps(ast.NodeTransformer):
            def visit_Assign(self,node):
                self.generic_visit(node)
                names=[t.id for t in node.targets if isinstance(t,ast.Name)]
                if 'counts' in names:return [node,ast.parse("if beginner_contacts and tier != 'HARD':\n    counts = [max(1,len(holds))]+([2] if not holds and len(event['lanes'])>=2 and maxcount>=2 and abs(bt-round(bt))<1e-4 else [])").body[0]]
                if 'd' in names:return [node,ast.parse('if beginner_contacts and (d > 2**.5 + 1e-7 or d/max(dt/1000,1e-8) > 3.5 + 1e-7):\n    ok=False\n    break').body[0]]
                if 'new_facing' in names:return [node,ast.parse('if beginner_contacts and abs(new_facing-old_facing)>60+1e-7:\n    continue').body[0]]
                return node
        tree=BeginnerCaps().visit(tree);ast.fix_missing_locations(tree)
        exec(compile(tree,'<v362_band_density_and_stricter_beginner_caps>','exec'),env)
        proposed=planner_level if planner_level is not None else TARGETS[band-1];speed,travel_band=travel(cols,proposed)
        # v363: the natural (human) foot reading of the rendered chart must stay
        # front-facing; otherwise retry the planner with other seeds.
        gates=[];variant=0;cap=max(6,len(events)//25);b=min(beam,32)  # v363 speed: beam32 first, full beam on NoRoute
        def conflict(ev):
            # A hold head is never dropped: omit the closest earlier free onset
            # (within 1s) that boxes the feet in instead.
            if ev is None or len(exclude)>=cap:return False
            if ev['holds']:
                ev=next((e for e in reversed(events) if e['ms']<ev['ms'] and ev['ms']-e['ms']<=1000 and not e['holds'] and e['index'] not in exclude),None)
                if ev is None:return False
            exclude.add(ev['index']);return True
        for retry in range(16):
            check_budget()
            try:result=env['compose'](events,cols,proposed,tier,b,seed+variant*7919,speed,pose_policy='soft',skill_weight=4.,recovery_policy='strict',skip_conflicts=max(0,cap-len(exclude)))
            except composer.NoRoute as error:
                if b<beam:b=beam;continue
                if error.event['holds'] and len(conflict_holds)<64:raise HoldConflict(error.event)
                if conflict(error.event):continue
                (out/'PLANNING_REJECTED.json').write_text(json.dumps(dict(event=error.event,error=str(error),excluded=sorted(exclude),augmentation=augmentation,target_density=density,planner_level=proposed,beam=beam,installed=False),indent=2))
                raise
            try:chart=sources.render(expanded,result['plan'],cols,proposed)
            except ValueError as gerr:
                # v363: PRIME allows <=24 rows/beat. Omit off-grid taps (ledgered); an off-grid
                # hold tail turns that hold into a tap (user-authorized conflict rule).
                if '>24 rows' not in str(gerr):raise
                def offgrid(i):
                    _,_,k,r=tl[i];rpb=expanded['splits'][k]['head'][8]&255
                    if rpb<=24:return False
                    g=max(d for d in range(1,25) if rpb%d==0);return r%(rpb//g)!=0
                by_index={e['index']:e for e in events};fixed=False
                for item in result['plan']:
                    ev=by_index.get(item['index'])
                    if ev is None:continue
                    if any(end>=0 and offgrid(end) for _,_,end in item['actions']) and len(conflict_holds)<64:raise HoldConflict(ev)
                    if offgrid(item['index']):
                        if not ev['holds']:fixed=conflict(ev) or fixed
                        elif ev['index'] not in exclude:exclude.add(ev['index']);fixed=True  # off-grid hold head: omitted (ledgered), PRIME cannot store it
                if not fixed:raise
                continue
            g=playability.gate(sources.events_of(chart)[1],cols,band);g.update(seed=seed+variant*7919,excluded=len(exclude));gates.append(g)
            if g['pass']:break
            # v363 speed: omit every flagged spot at once (ledgered) and recompose with
            # the same seed; only change seed when nothing more can be omitted.
            before=len(exclude)
            for at in g.get('problem_ms',[f[0] for f in g['first_flags']]):
                if not conflict(min(events,key=lambda e:abs(e['ms']-at))):break
            if len(exclude)==before:variant+=1
        if not gates:
            (out/'PLANNING_REJECTED.json').write_text(json.dumps(dict(error='every retry ended in NoRoute',excluded=sorted(exclude),target_density=density,planner_level=proposed,beam=beam,installed=False),indent=2))
            raise ValueError(f'NoRoute on every retry; {len(exclude)} conflicting onsets excluded')
        if not gates[-1]['pass']:
            (out/'PLAYABILITY_REJECTED.json').write_text(json.dumps(dict(gates=gates,planner_level=proposed,beam=beam,installed=False),indent=2))
            raise ValueError('PLAYABILITY_GATE natural reading not front-facing: '+json.dumps(gates[-1]['first_flags'][:3]))
        return chart,result,gates,expanded,additions,augmentation,tl,events,tier,proposed,speed,travel_band
    # v363 level calibration: the label is the frozen native-model estimate and must
    # fall inside the requested band; otherwise adjust density and regenerate.
    # v363 speed: predict the density from the selected source events (ms, no
    # composing); the composed chart is still measured and re-calibrated below.
    def predict(d):
        x,_,_=extend(source,d,seed=seed,avoid_added_windows=avoid_added_windows,verify=False);t,ev=sources.events_of(x)
        tier='EASY' if band<=2 else 'MEDIUM' if band==3 or (ref['chart']['level']>20 and not ref.get('source_is_original_ddr')) else 'HARD'
        chosen=selector(d,t[0][0],beginner_only=band==1)(ev,tier)[0]
        share=sum(len(e['lanes'])>=2 and not e['holds'] for e in chosen)/max(1,len(chosen))
        keep=1. if tier=='HARD' else min(1.,{'EASY':.14,'MEDIUM':.10}[tier]/max(share,1e-9))
        sim=[dict(e,lanes=e['lanes'][:1] if len(e['lanes'])>=2 and not e['holds'] and composer._h(seed,'jump',e['index'])>=keep else e['lanes'][:2 if cols==5 else 4]) for e in chosen]
        return MODEL.estimate(metrics(sim,t[0][0]),cols)[0]
    # v363 calibration. User decision 2026-10-23: when the music cannot reach the band
    # (or is too dense even at minimum), keep the closest chart with its REAL level.
    saturated=None
    if generation_only and target_density is None:
        lo_d,hi_d=None,None
        for _ in range(7):
            p=predict(density)
            if low<=p<=high:break
            if p<low and density>=9.-1e-9:break
            if p>high and density<=.2+1e-9:break
            if p<low:lo_d=density
            else:hi_d=density
            density=(lo_d*hi_d)**.5 if lo_d and hi_d else max(.2,min(9.,density*((low+high)/2/max(p,1))**1.15))
    tries=[];floor=ceiling=None;best=None;tier_override=[];thinned=[]
    for calib in range(6):
        while True:
            check_budget()
            try:attempt_out=attempt(density);break
            except (composer.NoRoute,ValueError) as ex:
                # v363: a too-dense source in HARD (keeps every onset) gets the density selector instead
                if band==4 and not tier_override and 'TIME_BUDGET' not in str(ex) and 'cannot be mapped' not in str(ex):
                    tier_override.append('MEDIUM');continue
                # last resort for boxed-in passages: thin the selection a little (up to 3 times)
                if ('NoRoute' in str(ex) or 'legal route' in str(ex)) and len(thinned)<3:
                    thinned.append(density);density=max(.2,density*.85);continue
                raise
            except HoldConflict as hc:
                # map the boxed-in hold head back to the pristine source and make it a tap
                _,orig=sources.events_of(pristine)
                hit=[(e['index'],lane) for e in orig if abs(e['ms']-hc.event['ms'])<.5 for _,lane in e['holds'] if lane in {l for _,l in hc.event['holds']}]
                if not hit or set(hit)<=set(conflict_holds):raise ValueError('NoRoute at hold head that cannot be mapped to a source hold')
                conflict_holds.extend(k for k in hit if k not in conflict_holds);source,hold_ledger=resimplify()
                (out/'whole_hold_simplification_ledger.json').write_text(json.dumps(hold_ledger,indent=2),encoding='utf8')
        chart,result,gates,expanded,additions,augmentation,tl,events,tier,proposed,speed,travel_band=attempt_out
        estimated,calibration=MODEL.estimate(metrics(sources.events_of(chart)[1],tl[0][0]),cols)
        tries.append(dict(density=round(density,3),estimated_level=estimated))
        gap=0 if low<=estimated<=high else (low-estimated if estimated<low else estimated-high)
        if best is None or gap<best[0]:best=(gap,attempt_out,estimated)
        if gap==0 or not generation_only:break
        if estimated>high and tier=='HARD' and not tier_override:
            tier_override.append('MEDIUM');continue  # source denser than the band: thin it instead of keeping all onsets
        if estimated<low and density>=9.-1e-9:saturated='music_too_sparse_for_band';break
        if estimated>high and density<=.2+1e-9:saturated='music_too_dense_for_band';break
        if estimated<low:floor=density
        else:ceiling=density
        density=(floor*ceiling)**.5 if floor and ceiling else max(.2,min(9.,density*((low+high)/2/max(estimated,1))**1.15))
    if best[0]>0:
        saturated=saturated or 'closest_after_calibration'
        chart,result,gates,expanded,additions,augmentation,tl,events,tier,proposed,speed,travel_band=best[1];estimated=best[2]
    if generation_only:
        chart['tags']=[(k,estimated if k==1001 else v) for k,v in chart['tags']];encoded=nx20.build(chart)
        receipt=dict(algorithm=ALGO.name,playability_gate=gates[-1],level_calibration_tries=tries,band_saturated=saturated,game_song_id=ref['game_song_id'],title=ref['title'],mode=ref['mode'],band=band,level_provisional=estimated,level_source='frozen native difficulty model estimate (anime_channel_dng/engine/difficulty_model.py)',tier=tier,reference=str(reference),reference_sha256=ref['sha256'],output_sha256=hashlib.sha256(encoded).hexdigest(),generation_only=True,review_status='UNREVIEWED_FOR_HUMAN_PLAYTEST',independent_validation_run=False,native_engine_tested=False,installed=False,human_playtest_pending=True,seconds=time.time()-start)
        (out/'candidate.NX').write_bytes(encoded)
        for name,value in [('receipt',receipt),('added_notes_ledger',additions),('difficulty_delta_ledger',result['ledger'])]:(out/(name+'.json')).write_text(json.dumps(value,indent=2),encoding='utf8')
        return receipt
    _,actual=sources.events_of(chart);actual_metrics=metrics(actual,tl[0][0]);level,calibration=MODEL.estimate(actual_metrics,cols)
    initial_validation=validate(expanded,chart,result['plan'],tl,events,cols,proposed,tier,result['ledger'],speed,pose_policy='guarded',recovery_policy='strict')
    if band==1 and initial_validation['pass']:
        beginner=(certify if cols==10 else certify_single)(actual_metrics,initial_validation['footmetrics'])
        if beginner:
            calibration=dict(beginner,general_corpus_estimate=level,general_corpus_proof=calibration);level=3
    if not low<=level<=high:
        (out/'OUT_OF_BAND.json').write_text(json.dumps(dict(estimated_level=level,requested_band=[low,high],calibration=calibration,augmentation=augmentation,target_density=density,planner_level=proposed,installed=False),indent=2))
        raise ValueError(f'Independent native-corpus level {level} outside requested band {low}..{high}; not relabelled')
    speed=min(speed,travel(cols,level)[0])
    verification=validate(expanded,chart,result['plan'],tl,events,cols,level,tier,result['ledger'],speed,pose_policy='guarded',recovery_policy='strict')
    if not verification['pass']:
        (out/'FINAL_LEVEL_REJECTED.json').write_text(json.dumps(dict(estimated_level=level,planner_level=proposed,target_density=density,verification=verification,installed=False),indent=2))
        raise ValueError('Independent v362 audit rejected: '+str(verification['errors'][:5]))
    chart['tags']=[(k,level if k==1001 else v) for k,v in chart['tags']];encoded=nx20.build(chart)
    receipt=dict(pass_=True,game_song_id=ref['game_song_id'],title=ref['title'],mode=ref['mode'],band=band,level_provisional=level,tier=tier,reference=str(reference),reference_sha256=ref['sha256'],output_sha256=hashlib.sha256(encoded).hexdigest(),augmentation=augmentation,independent_validation=verification,level_calibration=calibration,native_travel_band=travel_band,travel_bound=speed,target_density=density,planner_level=proposed,skipped_new_subdivision_windows=avoid_added_windows,whole_hold_simplifications=len(hold_ledger),original_reference_unchanged=True,installed=False,native_engine_tested=False,human_playtest_pending=True,seconds=time.time()-start)
    (out/'candidate.NX').write_bytes(encoded)
    for name,value in [('receipt',receipt),('added_notes_ledger',additions),('difficulty_delta_ledger',result['ledger']),('foot_plan',result['plan'])]:(out/(name+'.json')).write_text(json.dumps(value,indent=2),encoding='utf8')
    return receipt

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--reference',required=True);p.add_argument('--band',required=True,type=int,choices=(1,2,3,4));p.add_argument('--out',required=True);p.add_argument('--beam',type=int,default=64);a=p.parse_args()
    try:print(json.dumps(generate(a.reference,a.band,a.out,beam=a.beam)),flush=True)
    except Exception as e:
        o=Path(a.out);o.mkdir(parents=True,exist_ok=True);(o/'REJECTED.json').write_text(json.dumps(dict(error=str(e),reference=a.reference,band=a.band,installed=False),indent=2));print('BAND_REJECTED',str(e),flush=True);raise
