"""Bounds-checked RESPECT Unity TextAsset reader.

Format cross-checked against local DJMax-Editor TrailerChartReader.cs and
RESPECT2BMS. Preserve u32 ticks (the older converter reads only u16).
"""
import struct,math,bisect
def parse(data,name=''):
    def read(fmt,offset):
        size=struct.calcsize(fmt)
        if offset<0 or offset+size>len(data):raise ValueError(f'{name}: truncated at {offset}')
        return struct.unpack_from(fmt,data,offset)
    sign,end=read('<II',0)
    if sign!=0:raise ValueError(f'{name}: unexpected chart signature')
    instruments,track_word,resolution,tempo,last_tick,play_time,end_tick,unknown=read('<HHHfIfII',end)
    count=track_word&255
    if not 1<=count<=128 or not 1<=resolution<=4096 or not math.isfinite(tempo) or tempo<=0:raise ValueError('invalid trailer')
    if end+26!=len(data):raise ValueError('unexpected trailer length')
    pos=8;sounds={0:{'file':None,'flag':0}}
    for _ in range(instruments):
        sid,flag,text=read('<HB64s',pos);pos+=67
        filename=text.split(b'\0')[0].decode('utf8')
        if sid in sounds:raise ValueError('duplicate instrument')
        sounds[sid]={'file':filename,'flag':flag}
    tracks=[];bpms={0:tempo};unresolved=[]
    for index in range(count):
        read('<H',pos);pos+=2
        text,bound,events=read('<64sII',pos);pos+=72
        notes=[];controls=[]
        for _ in range(events):
            tick,code=read('<IB',pos)
            if code==1:
                sid,volume,pan,attribute,length,pad=read('<HBBBHB',pos+5)
                if sid not in sounds:unresolved.append({'track':index,'tick':tick,'sound':sid,'volume':volume,'length':length})
                notes.append({'tick':tick,'sound':sid,'volume':volume,'pan':pan,'attribute':attribute,'length':length})
            elif code==3:
                bpm=read('<f',pos+5)[0]
                if not math.isfinite(bpm) or bpm<=0:raise ValueError('invalid BPM')
                if tick in bpms and tick!=0 and abs(bpms[tick]-bpm)>1e-4:raise ValueError('conflicting tempo events')
                bpms[tick]=bpm
            elif code==2:controls.append({'tick':tick,'volume':read('<B',pos+5)[0]})
            elif code!=4:raise ValueError(f'unsupported opcode {code} at {pos}')
            pos+=13
        tracks.append({'index':index,'name':text.split(b'\0')[0].decode('utf8'),'bound':bound,'notes':notes,'volume_events':controls})
    if pos!=end:raise ValueError(f'track end mismatch {pos} != {end}')
    return {'name':name,'resolution':resolution,'ticks_per_beat':resolution/4,'tempo':tempo,'play_time':play_time,'end_tick':end_tick,'sounds':sounds,'bpms':sorted(bpms.items()),'tracks':tracks,'unresolved_instruments':unresolved}
def tick_seconds(chart,tick):
    t=0.;start=0;bpm=chart['bpms'][0][1];tpb=chart['ticks_per_beat']
    for at,value in chart['bpms'][1:]:
        if at>tick:break
        t+=(at-start)*60/(bpm*tpb);start=at;bpm=value
    return t+(tick-start)*60/(bpm*tpb)
def playable_tracks(chart):
    # Verified against Respect5kZoneRenderer.cs: side/scratch lanes are excluded.
    return chart['tracks'][3:8]
