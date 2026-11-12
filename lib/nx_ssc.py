"""PRIME NX chart -> StepMania 5 .ssc (pump-single / pump-double), exact against the game's clock.

Each chart carries its own timing (SM5 split timing): one BPM per NX split. A split is placed on the last 1/48-beat
grid line its start time reaches at the previous BPM (splits of BMS conversions can start a few ms before the
previous one ends), and the remainder (< one grid step, or a real pause) becomes a STOP. check() replays every
note through the written timing and returns the worst deviation from the NX time in ms."""
from fractions import Fraction as F
from pathlib import Path
import math,sys
sys.path[:0]=[str(Path(__file__).resolve().parent)]
from hybrid import nx20,sources

GRID=48   # StepMania stores 48 rows per beat
MAX_MS=3.  # rows finer than 1/48 beat (BMS 1/64, 1/192) round by <= half a grid step: ~1.7 ms at 180 BPM
SYMBOL={0x43:'1',0x57:'2',0x5F:'3'}   # tap, hold head, hold tail (0x5B = hold body, implied)

def q(beat):return F(round(beat*GRID),GRID)

def layout(nx):
    """Per split: (start beat on the grid, bpm, rows per beat, NX start ms); plus beat-0 ms, BPM changes and stops."""
    out=[];bpms,stops=[],[];last=None
    for k,s in enumerate(nx['splits']):
        h=s['head'];bpm,t,rpb=float(h[4]),float(h[3]),int(h[8])&255
        if not k:b=F(0);origin=t
        else:
            # NX times are float32: a split within 0.05 grid step of a line takes that line, else the line before it
            pb,pbpm,_,pt=out[-1];x=(t-pt)*pbpm/60000*GRID;b=pb+F(round(x) if abs(x-round(x))<.05 else math.floor(x),GRID)
            gap=t-(pt+float(b-pb)*60000/pbpm)
            if gap>.01:stops.append((b,gap/1000))
        out.append((b,bpm,rpb,t))
        if bpm!=last:bpms.append((b,bpm));last=bpm
    return out,origin,bpms,stops

def timing(nx):
    _,origin,bpms,stops=layout(nx);return origin,bpms,stops

def placed(nx):
    """(beat, NX ms, row) for every non-empty row."""
    lay=layout(nx)[0]
    for k,s in enumerate(nx['splits']):
        b,bpm,rpb,t=lay[k]
        for r,row in enumerate(s['rows']):
            if row is not None:yield b+F(r,rpb),t+r*60000/bpm/rpb,row

def notes(nx):
    rows={};bad=0
    for beat,ms,row in placed(nx):
        for lane,v in enumerate(row):
            kind=v&255
            if not v or kind==0x5B:continue
            if kind not in SYMBOL:bad+=1;continue
            rows.setdefault(q(beat),['0']*nx['cols'])[lane]=SYMBOL[kind]
    return rows,bad

def time_of(beat,origin,bpms,stops):
    t=origin;b0,bpm=F(0),bpms[0][1]
    for b,v in bpms[1:]:
        if b>beat:break
        t+=float(b-b0)*60000/bpm;b0,bpm=b,v
    t+=float(beat-b0)*60000/bpm
    return t+sum(s*1000 for b,s in stops if b<=beat)

def check(nx):
    origin,bpms,stops=timing(nx);worst=0.
    for beat,ms,row in placed(nx):
        if any(v and (v&255)!=0x5B for v in row):worst=max(worst,abs(time_of(q(beat),origin,bpms,stops)-ms))
    return worst

def measures(rows,cols):
    last=int(max(rows)//4) if rows else 0;out=[]
    for m in range(last+1):
        es=[(b-4*m,v) for b,v in rows.items() if 4*m<=b<4*m+4]
        per=4;  # rows per measure: smallest that holds every note
        for b,_ in es:per=math.lcm(per,(b/4).denominator)
        grid=[['0']*cols for _ in range(per)]
        for b,v in es:grid[int(b*per/4)]=v
        out.append('\n'.join(''.join(r) for r in grid))
    return ',\n'.join(out)

def fmt(x):return f'{float(x):.6f}'

def chart_block(nx,name,level,difficulty,description,credit):
    origin,bpms,stops=timing(nx);rows,bad=notes(nx)
    if bad:raise ValueError(f'{name}: {bad} cells of an unsupported kind')
    head=[('NOTEDATA',''),('CHARTNAME',name),('STEPSTYPE','pump-single' if nx['cols']==5 else 'pump-double'),
          ('DESCRIPTION',description),('CHARTSTYLE',''),('DIFFICULTY',difficulty),('METER',str(level)),('CREDIT',credit),
          ('OFFSET',fmt(-origin/1000)),('BPMS',','.join(f'{fmt(b)}={v:.6f}' for b,v in bpms)),
          ('STOPS',','.join(f'{fmt(b)}={s:.6f}' for b,s in stops)),('DELAYS',''),('WARPS',''),('TIMESIGNATURES','0.000000=4=4'),
          ('TICKCOUNTS','0.000000=4'),('COMBOS','0.000000=1'),('SPEEDS','0.000000=1.000000=0.000000=0'),
          ('SCROLLS','0.000000=1.000000'),('FAKES',''),('LABELS','0.000000=Song Start')]
    return '\n'.join(f'#{k}:{v};' for k,v in head)+'\n#NOTES:\n'+measures(rows,nx['cols'])+'\n;\n'

def clean(s):return str(s).replace(';',',').replace('#','').replace(':',' ').replace('\n',' ').strip()

def song_ssc(title,artist,music,banner,sample_start,charts):
    """charts: list of (nx_dict, name, level, description, credit); difficulties assigned per mode by level."""
    first=charts[0][0];origin,bpms,stops=timing(first)
    head=[('VERSION','0.83'),('TITLE',clean(title)),('SUBTITLE',''),('ARTIST',clean(artist)),('GENRE','PIU OMNIMIX TEST'),
          ('CREDIT','PIU omnimix'),('BANNER',banner or ''),('BACKGROUND',banner or ''),('MUSIC',music),
          ('OFFSET',fmt(-origin/1000)),('SAMPLESTART',f'{sample_start:.3f}'),('SAMPLELENGTH','12.000'),('SELECTABLE','YES'),
          ('BPMS',','.join(f'{fmt(b)}={v:.6f}' for b,v in bpms)),('STOPS',','.join(f'{fmt(b)}={s:.6f}' for b,s in stops)),
          ('DELAYS',''),('WARPS',''),('TIMESIGNATURES','0.000000=4=4'),('TICKCOUNTS','0.000000=4'),('COMBOS','0.000000=1'),
          ('SPEEDS','0.000000=1.000000=0.000000=0'),('SCROLLS','0.000000=1.000000'),('FAKES',''),('LABELS','0.000000=Song Start')]
    text='\n'.join(f'#{k}:{v};' for k,v in head)+'\n'
    for cols in (5,10):
        mine=sorted([c for c in charts if c[0]['cols']==cols],key=lambda c:c[2])
        names=['Beginner','Easy','Medium','Hard','Challenge']
        for i,(nx,name,level,desc,credit) in enumerate(mine):
            text+='\n//---------------'+name+'---------------\n'+chart_block(nx,name,level,names[i] if i<5 else 'Edit',desc,credit)
    return text

if __name__=='__main__':   # self-check: a 2-split chart with a gap and a BPM change lands every note on its NX time
    import glob
    worst=0;n=0
    for p in glob.glob(r'D:\EZ2ON_PIU\runs\*\lead\*.NX')[:40]+glob.glob(r'D:\Pump It Up Data\PIU\final_generation_v362\runs\v365_full_01\songs\0000DA33\*.NX'):
        nx=nx20.parse(Path(p).read_bytes());worst=max(worst,check(nx));n+=1
    print('NX_SSC_SELF_CHECK',n,'charts; worst note deviation',round(worst,3),'ms');assert worst<MAX_MS
