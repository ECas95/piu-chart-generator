"""Doubles = PumpDoublify of the same-band generated Single (user decision 2026-10-23).

For every pending Double job whose Single of the same band is registered:
  PumpDoublify -> natural-reading gate -> if flagged, omit those notes in the Single input
  (ledgered) and convert again (max 5) -> label with the native-model level.
Results: runs/<run>/charts/<key>/attempt_01 + DOUBLIFY_REGISTRY.json (merged by the catalog builder).
Jobs that cannot pass stay pending for the regular Double generator.
"""
from pathlib import Path
import sys,json,hashlib,time,os,argparse,copy
from concurrent.futures import ProcessPoolExecutor,as_completed
R=Path(__file__).resolve().parent
sys.path[:0]=[str(R)]
TARGET=[3,9,15,19]
read=lambda p:json.loads(Path(p).read_text(encoding='utf8'))

def strip_rows(nx,ms_list):
    """Remove every note starting at the flagged instants (holds lose head..tail)."""
    from hybrid import sources
    tl,events=sources.events_of(nx);out=copy.deepcopy(nx);removed=[]
    for e in events:
        if not any(abs(e['ms']-m)<1. for m in ms_list):continue
        ends={lane:end for end,lane in e['holds']}
        for lane in e['lanes']:
            last=ends.get(lane,e['index'])
            for i in range(e['index'],last+1):
                _,_,k,r=tl[i];row=list(out['splits'][k]['rows'][r] or [0]*out['cols']);row[lane]=0
                out['splits'][k]['rows'][r]=tuple(row) if any(row) else None
            removed.append(dict(ms=e['ms'],beat=e['beat'],lane=lane,hold=lane in ends))
    from hybrid import nx20
    return nx20.parse(nx20.build(out)),removed

def work(job,single_nx,out_dir):
    import playability,generate_nx_band as G
    from pumpdoublify_adapter import convert,nx20
    from hybrid import sources
    t=time.time();key=job['key'];band=job['band'];folder=Path(out_dir)/key/'attempt_01'
    if (folder/'receipt.json').exists():return key,json.loads((folder/'receipt.json').read_text())
    folder.mkdir(parents=True,exist_ok=True)
    src=nx20.parse(Path(single_nx).read_bytes());ledger=[];seed=int.from_bytes(hashlib.sha256(key.encode()).digest()[:4],'little')
    try:
        for attempt in range(6):
            out,res,recipe=convert(src,level=TARGET[band-1],seed=seed,beam=64,verify=False)
            tl,ev=sources.events_of(out);g=playability.gate(ev,10,band)
            if g['pass']:break
            if attempt==5 or not g['problem_ms']:raise ValueError('doublify gate: '+json.dumps(g['first_flags'][:3]))
            src,removed=strip_rows(src,g['problem_ms']);ledger.append(dict(attempt=attempt,removed=removed))
        level=G.MODEL.estimate(G.metrics(ev,tl[0][0]),10)[0]
        out['tags']=[(k,level if k==1001 else v) for k,v in out['tags']];data=nx20.build(out)
        (folder/'candidate.NX').write_bytes(data)
        receipt=dict(game_song_id=job['game_song_id'],mode='Double',band=band,level_provisional=level,level_source='frozen native difficulty model estimate',
                     method='PumpDoublify of same-band generated Single + natural-reading gate repair',single_source=str(single_nx),
                     omitted_single_notes=sum(len(x['removed']) for x in ledger),playability_gate=g,output_sha256=hashlib.sha256(data).hexdigest(),
                     review_status='UNREVIEWED_FOR_HUMAN_PLAYTEST',installed=False,seconds=time.time()-t)
        (folder/'doublify_ledger.json').write_text(json.dumps(ledger,indent=1));(folder/'receipt.json').write_text(json.dumps(receipt,indent=1))
        return key,receipt
    except Exception as e:
        (folder/'REJECTED.json').write_text(json.dumps(dict(error=str(e)[:500],seconds=time.time()-t),indent=1));return key,None

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--workers',type=int,default=11);p.add_argument('--limit',type=int,default=0);a=p.parse_args()
    jobs=read(R/'generation_jobs.json')['jobs'];scope=set(read(R/'USER_CHANNEL_SCOPE.json')['song_ids'])
    reg=read(R/'GENERATED_ONLY_REGISTRY.json')['records'];dpath=R/'DOUBLIFY_REGISTRY.json'
    dreg=read(dpath) if dpath.exists() else dict(records={},method='PumpDoublify of same-band Single',review_status='UNREVIEWED_FOR_HUMAN_PLAYTEST')
    todo=[]
    for j in jobs:
        if j['mode']!='Double' or j['game_song_id'] not in scope or j['key'] in reg or j['key'] in dreg['records']:continue
        s=reg.get(f"{j['game_song_id']}_Single_B{j['band']}")
        if s:todo.append((j,s['nx']))
    if a.limit:todo=todo[:a.limit]
    out=R/'runs'/a.run/'charts';out.mkdir(parents=True,exist_ok=True)
    print('DOUBLIFY_START',len(todo),flush=True);done=ok=0
    def save():
        tmp=dpath.with_suffix('.json.tmp');tmp.write_text(json.dumps(dreg,indent=1),encoding='utf8');os.replace(tmp,dpath)
    with ProcessPoolExecutor(a.workers) as ex:
        futs=[ex.submit(work,j,nx,str(out)) for j,nx in todo]
        for f in as_completed(futs):
            key,rc=f.result();done+=1
            if rc:
                ok+=1;nxp=out/key/'attempt_01/candidate.NX'
                dreg['records'][key]=dict(key=key,game_song_id=rc['game_song_id'],mode='Double',band=rc['band'],target_level=rc['level_provisional'],nx=str(nxp),receipt=str(nxp.with_name('receipt.json')),review_status='UNREVIEWED_FOR_HUMAN_PLAYTEST',algorithm='v363-doublify')
            if done%100==0:save();print('DOUBLIFY_PROGRESS',done,len(todo),'ok',ok,flush=True)
    save();print('DOUBLIFY_FINISHED',done,'ok',ok,flush=True)

if __name__=='__main__':main()
