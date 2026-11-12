"""Use PumpDoublify's route search on PIU Singles without its destructive serializer.

The supplied vendor code is immutable. A reviewed AST adaptation returns only
its panel proposal. The hybrid contact solver checks that proposal while keeping
the original NX clock and hold identities. Rejections are explicit.
"""
from pathlib import Path
import sys,ast,inspect,importlib.util,hashlib,random
from itertools import permutations

R=Path(__file__).resolve().parent
sys.path.insert(0,str(R))
from hybrid import sources,nx20,composer
from hybrid.validation import validate

def load_vendor():
    path=R/'pumpdoublify/pumpdoublify.py'
    spec=importlib.util.spec_from_file_location('frozen_pumpdoublify',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module,path

def propose_panels(source,seed=362):
    if source['cols']!=5:raise ValueError('PumpDoublify adapter requires a five-panel Pump Single')
    _,events=sources.events_of(source)
    if not events:raise ValueError('Empty source chart')
    for event in events:
        if len(event['lanes'])>2:raise ValueError(f"Source row {event['index']} has more than two heads; no silent chord reduction")
    vendor,path=load_vendor()
    tree=ast.parse(inspect.getsource(vendor.doublify_measures));fn=tree.body[0]
    # Return the proposed sequence before the old output code can delete a head,
    # cancel a hold, or pair a tail with an arbitrary open hold.
    stop=next(i for i,node in enumerate(fn.body) if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='double_step_index' for t in node.targets))
    fn.body=fn.body[:stop]+[ast.Return(value=ast.Name(id='double_steps',ctx=ast.Load()))]
    ast.fix_missing_locations(tree)
    env=dict(vendor.__dict__)
    def exact_times(changes,beats):
        return [events[min(len(events)-1,round(beat*len(events)/4))]['ms']/1000 for beat in beats]
    env['beats_to_times']=exact_times
    # Use a local Random so importing or running the adapter does not reseed callers.
    env['random']=random.Random(seed)
    exec(compile(tree,'<pumpdoublify_route_only>','exec'),env)
    measure=[]
    for event in events:
        held={lane for _,lane in event['holds']}
        measure.append(bytes(ord('2') if lane in held else ord('1') if lane in event['lanes'] else ord('0') for lane in range(5)))
    route=env['doublify_measures']([measure],[(0.,120.)])
    if route is None:raise ValueError('PumpDoublify returned no route; no source notes changed')
    assert len(route)==sum(len(e['lanes']) for e in events),'PumpDoublify head-count discrepancy'
    fixed={};cursor=0
    for event in events:
        n=len(event['lanes']);lanes=tuple(route[cursor:cursor+n]);cursor+=n
        assert len(set(lanes))==n,'PumpDoublify placed two heads in the same cell'
        fixed[event['index']]=lanes
    return fixed,dict(vendor_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),seed=seed,route_only=True,source_columns=5,heads=len(route),holds_in_original_serializer_never_used=True,exact_source_attack_seconds_supplied=True)

def fixed_contact_composer():
    tree=ast.parse(inspect.getsource(composer.compose));fn=tree.body[0]
    fn.args.args.append(ast.arg(arg='fixed_routes'));fn.args.defaults.append(ast.Constant(value=None))
    fn.args.args.append(ast.arg(arg='strict_route'));fn.args.defaults.append(ast.Constant(value=True))
    class LimitPanels(ast.NodeTransformer):
        def visit_Assign(self,node):
            self.generic_visit(node)
            if any(isinstance(t,ast.Name) and t.id=='lane_options' for t in node.targets):
                extra=ast.parse('if fixed_routes is not None and strict_route:\n    lane_options = permutations(fixed_routes[ix], count)').body[0]
                return [node,extra]
            if any(isinstance(t,ast.Name) and t.id=='preferred' for t in node.targets):
                extra=ast.parse('if fixed_routes is not None:\n    cost += pump_route_penalty(ix, lanes, fixed_routes, distance)').body[0]
                return [node,extra]
            return node
    tree=LimitPanels().visit(tree);ast.fix_missing_locations(tree)
    env=dict(composer.__dict__);env['permutations']=permutations
    env['pump_route_penalty']=lambda ix,lanes,routes,distance: .9*(sum(min(distance(a,b) for b in routes[ix]) for a in lanes)+sum(min(distance(a,b) for b in lanes) for a in routes[ix]))
    exec(compile(tree,'<hybrid_fixed_pumpdoublify_contact_route>','exec'),env)
    return env['compose']

def convert(source,level=18,seed=362,beam=64,verify=True):
    fixed,proof=propose_panels(source,seed)
    tl,events=sources.events_of(source)
    # Unchanged constraints: no relaxed travel, hold recovery, spin or contacts.
    speed=5+level*.10
    solve=fixed_contact_composer()
    try:
        result=solve(events,10,level,'HARD',beam,seed,speed,pose_policy='guarded',skill_weight=4.,recovery_policy='strict',fixed_routes=fixed)
        proof['pump_proposal_panel_adjustments']=[]
    except composer.NoRoute as error:
        # PumpDoublify's old route search ignores held contacts. Keep its proposal
        # as a cost preference and let the SAME guarded solver find legal panels.
        # The source event/hold set and every physical bound remain unchanged.
        proof['fixed_panel_route_rejection']=str(error)
        result=solve(events,10,level,'HARD',beam,seed,speed,pose_policy='guarded',skill_weight=4.,recovery_policy='strict',fixed_routes=fixed,strict_route=False)
        proof['pump_proposal_panel_adjustments']=[dict(index=e['index'],proposal=list(fixed[e['index']]),actual=[a[0] for a in e['actions']],reason='hold-aware guarded contact solver; source heads/times/holds unchanged') for e in result['plan'] if set(a[0] for a in e['actions'])!=set(fixed[e['index']])]
    out=sources.render(source,result['plan'],10,level)
    if not verify:
        proof.update(independent_validation_run=False,native_engine_tested=False,review_status='UNREVIEWED_FOR_HUMAN_PLAYTEST',installed=False)
        return out,result,proof
    verification=validate(source,out,result['plan'],tl,events,10,level,'HARD',result['ledger'],speed,pose_policy='guarded',recovery_policy='strict')
    if not verification['pass']:raise ValueError('Independent contact/hold validator rejected PumpDoublify route: '+str(verification['errors'][:5]))
    proof.update(verification=verification,contact_constraints_unchanged=True,head_and_hold_timing_preserved=True,native_engine_tested=False,installed=False)
    return out,result,proof
