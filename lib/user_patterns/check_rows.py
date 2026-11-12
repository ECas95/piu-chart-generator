"""Review row patterns (jumps/holds/rests) with the natural-reading gate: 8th rows at 130-190 BPM, original + mirror."""
import sys,json
sys.path[:0]=[r'D:\Pump It Up Data\PIU\final_generation_v362']
import playability
P={'DL':0,'UL':1,'C':2,'UR':3,'DR':4}
def events(rows,bpm,mirror):
    step=60000/bpm/2;ev=[];ends={}
    for r,items in enumerate(rows):
        lanes=[];holds=[]
        for it in items:
            lane,_,h=it.partition('~');lane=P[lane];lane=4-lane if mirror else lane
            lanes.append(lane)
            if h:holds.append((r+int(h),lane))
        if lanes:ev.append(dict(index=r,ms=1000+r*step,beat=r/2,lanes=lanes,holds=holds,hold_ends_ms={e:1000+e*step for e,_ in holds}))
    return ev
if __name__=='__main__':
    pats=[p for p in json.load(open(sys.argv[1],encoding='utf8'))['patterns'] if 'rows' in p]
    for p in pats:
        res=[]
        for band in (2,3,4):
            ok=all(playability.gate(events(p['rows'],bpm,m),5,band)['pass'] for bpm in (130,150,170,190) for m in (0,1))
            res.append(f"b{band}:{'PASS' if ok else 'FAIL'}")
        a=playability.assess(events(p['rows'],150,0),5)
        print(p['id'],' '.join(res),'worst_yaw',a['worst_yaw'],'cross',a.get('crossovers'),'back',a.get('back_facing'),a['first_flags'][:3])
