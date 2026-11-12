import sys,json
sys.path[:0]=[r'D:\Pump It Up Data\PIU\final_generation_v362']
import playability
P={'DL':0,'UL':1,'C':2,'UR':3,'DR':4}
pats=json.load(open(r'D:\Pump It Up Data\PIU\final_generation_v362\vendor_v363\hybrid\user_patterns_single.json',encoding='utf8'))['patterns']
pats=[p for p in pats if 'panels' in p]
for bpm in (130,150,170,190):
    for p in pats:
        lanes=[P[x] for x in p['panels']]
        mirror=[4-l for l in lanes]
        for name,ls in (('orig',lanes),('mirror',mirror)):
            ev=[dict(index=i,ms=1000+i*60000/bpm/4,beat=i/4,lanes=[l],holds=[],hold_ends_ms={}) for i,l in enumerate(ls)]
            g=playability.gate(ev,5,4)
            print(bpm,p['id'],name,'PASS' if g['pass'] else 'FAIL',g.get('worst_yaw'),g.get('back_facing'),g.get('twists'),g.get('fast_doublesteps'),g['first_flags'][:2])
