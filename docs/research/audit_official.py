"""Read native official NX20 default blocks; summarize musical/physical features."""
from pathlib import Path
from collections import Counter, defaultdict
import struct, json, sys, statistics, math
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_chart_revisions import native, rows

ROOT=Path(__file__).resolve().parent
def read_events(data):
    magic,start,cols,light,nt=struct.unpack_from('<4s4I',data)
    if magic!=b'NX20' or cols not in (5,10) or start:return None
    pos=20+nt*8;ns=struct.unpack_from('<I',data,pos)[0];pos+=4
    events=[];beat=0.; bpmvals=[]; branches=0
    for _ in range(ns):
        system,nmeta=struct.unpack_from('<II',data,pos);pos+=8+8*nmeta
        nb=struct.unpack_from('<I',data,pos)[0];pos+=4;branches+=nb>1
        for bi in range(nb):
            h=struct.unpack_from('<5f2I',data,pos);pos+=28+8*h[6]
            nr=struct.unpack_from('<I',data,pos)[0];pos+=4
            ms,bpm=h[:2];rpb=h[5]&255
            if not math.isfinite(bpm) or bpm<=0 or not rpb:return None
            if bi==0:bpmvals.append(bpm)
            for ri in range(nr):
                w=struct.unpack_from('<I',data,pos)[0]
                if w&255==128:pos+=4;continue
                cells=struct.unpack_from(f'<{cols}I',data,pos);pos+=4*cols
                if bi:continue
                hit=tuple(c for c,v in enumerate(cells) if v&255 in (67,87))
                hs=tuple(c for c,v in enumerate(cells) if v&255==87)
                active=tuple(c for c,v in enumerate(cells) if v&255 in (87,91,95))
                if hit:events.append({'beat':beat+ri/rpb,'ms':ms+ri*60000/bpm/rpb,'lanes':hit,'holds':hs,'active':active})
            if bi==0:beat+=nr/rpb
    ps=struct.unpack_from('<I',data,len(data)-4)[0]
    assert pos==len(data)-ps
    return cols,events,bpmvals,branches

def peak(times,secs):
    end=0;hi=0
    for start,t in enumerate(times):
        while end<len(times) and times[end]<t+secs*1000:end+=1
        hi=max(hi,end-start)
    return hi/secs

def metrics(cols,ev):
    if len(ev)<2:return None
    ev=sorted(ev,key=lambda x:x['ms'])
    times=[e['ms'] for e in ev];span=(times[-1]-times[0])/1000
    if span<=0:return None
    notes=sum(len(e['lanes']) for e in ev)
    transitions=list(zip(ev,ev[1:]));rapid=[(a,b) for a,b in transitions if 0<b['ms']-a['ms']<=250]
    singles=[e for e in ev if len(e['lanes'])==1]
    rapid_single=[(a,b) for a,b in zip(singles,singles[1:]) if 0<b['ms']-a['ms']<=250]
    def frac(n,d):return n/d if d else 0
    result={'notes':notes,'rows':len(ev),'span_s':span,'note_nps':notes/span,'row_nps':len(ev)/span,
            'peak_row_1s':peak(times,1),'peak_row_4s':peak(times,4),'peak_row_8s':peak(times,8),
            'jump_rows':frac(sum(len(e['lanes'])==2 for e in ev),len(ev)),
            'triple_rows':frac(sum(len(e['lanes'])>=3 for e in ev),len(ev)),
            'hold_heads':frac(sum(len(e['holds']) for e in ev),notes),
            'hold_contact_rows':frac(sum(bool(e['active']) for e in ev),len(ev)),
            'rapid_jacks':frac(sum(a['lanes']==b['lanes'] for a,b in rapid_single),len(rapid_single)),
            'rapid_row_repeat':frac(sum(a['lanes']==b['lanes'] for a,b in rapid),len(rapid)),
            'offbeat_rows':frac(sum(abs(e['beat']-round(e['beat']))>1e-5 for e in ev),len(ev)),
            'sixteenth_rows':frac(sum(abs(e['beat']*2-round(e['beat']*2))>1e-5 for e in ev),len(ev))}
    if cols==10:
        result['cross_pad_single_transition']=frac(sum((a['lanes'][0]<5)!=(b['lanes'][0]<5) for a,b in rapid_single),len(rapid_single))
        result['wide_double_jump']=frac(sum(len(e['lanes'])==2 and min(e['lanes'])<2 and max(e['lanes'])>7 for e in ev),len(ev))
    return result

def quant(vals):
    vals=sorted(vals)
    if not vals:return None
    return {f'p{p}':round(vals[min(len(vals)-1,round((len(vals)-1)*p/100))],4) for p in (10,50,75,90,95)}

def main():
    rr=[];errs=Counter();patterns=defaultdict(Counter)
    for game,base in [('XX',Path(r'E:\PIIUUUU\PIU_XX_F19_NATIVO\D')),('PH',Path(r'E:\PIIUUUU\PIU_PHOENIX_F23_NATIVO\D'))]:
        cat=native.read_list(base)
        for r in rows(cat):
            if r['mode'] not in (0,2) or not 1<=r['level']<=28:continue
            path=base/f'{r["folder"]:X}'/f'{r["folder"]:X}'/(r['name']+'.NX')
            if not path.exists():errs['missing']+=1;continue
            try:
                c=read_events(path.read_bytes())
                if not c:errs['excluded_nonstandard']+=1;continue
                cols,ev,bpms,branches=c
                m=metrics(cols,ev)
                if not m:errs['no_events']+=1;continue
                rr.append({'game':game,'song':r['song'],'title':r['title'],'path':str(path),'mode':r['mode'],'level':r['level'],'branches':branches,**m})
                # Ordered rhythm+panel patterns, no holds/jumps. Keep <=8th for low levels etc.
                for a in range(len(ev)-3):
                    group=ev[a:a+4]
                    if any(len(e['lanes'])!=1 or e['holds'] for e in group):continue
                    gaps=tuple(round(group[i+1]['beat']-group[i]['beat'],4) for i in range(3))
                    if not all(0<g<=1 for g in gaps):continue
                    lanes=tuple(e['lanes'][0] for e in group)
                    band=(r['level']-1)//5*5+1
                    patterns[(cols,band)][(gaps,lanes)]+=1
            except Exception as e:errs[type(e).__name__]+=1
        print(game,'loaded',len(rr),'errors',dict(errs),flush=True)
    summary=[]
    for cols in (5,10):
        for low,high in [(1,5),(6,10),(11,15),(16,20),(21,28)]:
            vals=[r for r in rr if r['mode']==(0 if cols==5 else 2) and low<=r['level']<=high]
            if not vals:continue
            summary.append({'columns':cols,'levels':[low,high],'charts':len(vals),'metrics':{k:quant([r[k] for r in vals]) for k in vals[0] if isinstance(vals[0][k],float)}})
    motif={f'{cols}_{band}':[{'gaps':g,'lanes':p,'count':n} for (g,p),n in co.most_common(100)] for (cols,band),co in patterns.items()}
    (ROOT/'official_chart_metrics.json').write_text(json.dumps({'charts':rr,'summary':summary,'errors':dict(errs)},indent=2),encoding='utf8')
    (ROOT/'official_short_motifs.json').write_text(json.dumps(motif,indent=2),encoding='utf8')
    print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
