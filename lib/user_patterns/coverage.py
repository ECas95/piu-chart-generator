"""Compare installed (PIU OMNIMIX PRUEBA) vs regenerated (v2) Single charts: notes, share of single taps inside a user
panel sequence (5+ consecutive panels of a pattern or its mirror), row patterns found literally (8ths, jumps, holds),
natural-reading crossovers / backwards."""
import sys,json,re
from pathlib import Path
sys.path[:0]=[r'D:\Pump It Up Data\PIU\final_generation_v362']
import playability
SONGS=Path(r'D:\003 - StepP1\SP2\stepp1-plus-2.0.0\Songs')
BANK=json.load(open(r'D:\Pump It Up Data\PIU\final_generation_v362\vendor_v363\hybrid\user_patterns_single.json',encoding='utf8'))['patterns']
P={'DL':0,'UL':1,'C':2,'UR':3,'DR':4};N=5
pats=[[P[x] for x in u['panels']] for u in BANK if 'panels' in u]
grams={tuple(s[i:i+N]) for p in pats for s in (p,[4-l for l in p]) for i in range(len(s)-N+1)}
RP=[[(r,sorted((P[i.partition('~')[0]],int(i.partition('~')[2] or 0)) for i in it)) for r,it in enumerate(u['rows']) if it] for u in BANK if 'rows' in u]

def charts(ssc):
    for block in ssc.split('#NOTEDATA:;')[1:]:
        if 'pump-single' not in block:continue
        meter=int(re.search(r'#METER:(\d+);',block).group(1));name=re.search(r'#CHARTNAME:([^;]*);',block).group(1)
        rows=[];full=[];beat=0
        for m in block.split('#NOTES:')[1].split(';')[0].strip().split(','):
            lines=[l.strip() for l in m.strip().splitlines() if l.strip()]
            for i,l in enumerate(lines):
                b=beat+4*i/len(lines)
                if any(c in '12' for c in l):rows.append((b,[k for k,c in enumerate(l) if c in '12']))
                if any(c in '123' for c in l):full.append((b,l))
            beat+=4
        yield name,meter,rows,full

def row_hits(full):
    tails={};heads={}
    for b,l in full:
        for k,c in enumerate(l):
            if c=='3':tails.setdefault(k,[]).append(b)
    for b,l in full:
        cells=[(k,0) if c=='1' else (k,round((min((t for t in tails.get(k,[]) if t>b),default=b)-b)/.5)) for k,c in enumerate(l) if c in '12']
        if cells:heads[round(b,4)]=cells
    hits=0
    for b0 in heads:
        for pat in RP:
            for flip in (0,1):
                if all(sorted((4-k if flip else k,h) for k,h in heads.get(round(b0+.5*(r-pat[0][0]),4),[(-9,0)]))==cells for r,cells in pat):hits+=1
    return hits

def stats(rows):
    taps=[r[1][0] for r in rows if len(r[1])==1];cov=set()
    for i in range(len(taps)-N+1):
        if tuple(taps[i:i+N]) in grams:cov.update(range(i,i+N))
    ev=[dict(index=i,ms=b*400.,beat=b,lanes=l,holds=[],hold_ends_ms={}) for i,(b,l) in enumerate(rows)]   # 150 BPM
    a=playability.assess(ev,5)
    return len(rows),len(cov)/max(1,len(taps)),a.get('crossovers',0),a.get('back_facing',0)

for d in sorted((SONGS/'PIU OMNIMIX PRUEBA v2').iterdir()):
    old={m:(r,f) for n,m,r,f in charts((SONGS/'PIU OMNIMIX PRUEBA'/d.name/'song.ssc').read_text(encoding='utf8'))}
    for name,meter,rows,full in charts((d/'song.ssc').read_text(encoding='utf8')):
        if meter<6:continue
        n,c,x,b=stats(rows);o=min(old,key=lambda m:abs(m-meter));on,oc,ox,ob=stats(old[o][0])
        print(f"{d.name[:26]:26} {name:13} notas {on:4}->{n:4}  secuencias {oc:4.0%}->{c:4.0%}  filas {row_hits(old[o][1]):2}->{row_hits(full):2}  cruces {ox:3}->{x:3}  espaldas {ob}->{b}")
