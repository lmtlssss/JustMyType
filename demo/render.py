#!/usr/bin/env python3
"""Render a measured fixture replay. Needs Pillow and ffmpeg; no network."""
from __future__ import annotations
import argparse
import json
import math
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H, FPS, DURATION = 1920, 1080, 30, 34
PAPER, INK = (240, 239, 232), (18, 18, 18)


def find_font(mono=False):
    names = ['DejaVuSansMono.ttf', 'LiberationMono-Regular.ttf'] if mono else ['DejaVuSans.ttf', 'LiberationSans-Regular.ttf']
    for name in names:
        try: return ImageFont.truetype(name, 24).path
        except OSError: pass
    raise RuntimeError('Install a system DejaVu or Liberation font. Font files are not part of this repository.')


def ease(x):
    x = min(1, max(0, x))
    return x*x*(3-2*x)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--proof',type=Path,required=True)
    p.add_argument('--holdout',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--frames',type=Path)
    a=p.parse_args()
    proof=json.loads(a.proof.read_text()); report=json.loads(a.holdout.read_text())
    if not proof.get('passed') or not report.get('complete'):
        p.error('The clip requires complete real measurements; no invented success fallback.')
    if proof['guarded']['verdict']['policy_sha256'] != report['policy_sha256']:
        p.error('Demo and holdout used different policies.')
    mono_path, sans_path = find_font(True), find_font(False)
    fonts={}
    def font(size,mono=False):
        key=(size,mono)
        if key not in fonts: fonts[key]=ImageFont.truetype(mono_path if mono else sans_path,size)
        return fonts[key]
    metrics=report['metrics'];total=len(report['cases'])
    count=proof['record_count']
    rows=[(x%100, x//100) for x in range(count)]
    def frame(t):
        dark = t < 3.8 or t >= 28
        bg, fg = (INK,PAPER) if dark else (PAPER,INK)
        im=Image.new('RGB',(W,H),bg); d=ImageDraw.Draw(im)
        def text(x,y,value,size=32,mono=False):
            d.text((x,y),value,font=font(size,mono),fill=fg,stroke_width=0)
        def line(y): d.line((110,y,1810,y),fill=fg,width=2)
        # Registration, not decoration: stable baseline and case identity.
        text(110,58,'JUSTMYTYPE / FIELD TEST 001',25,True)
        text(1450,58,'CODEX + TYPESAFE',25,True)
        line(108)
        if t < 3.8:
            text(105,270,'One wrong target.',104)
            text(110,445,'10,000 invoice records.',72)
            text(110,620,"it's not you. it's your arguments.",34,True)
            d.line((110,790,110+int(1700*ease(t/3.5)),790),fill=fg,width=3)
        elif t < 8.2:
            s=t-3.8
            text(110,155,'THE REQUEST',28,True)
            text(110,235,'Clean the build output.',78)
            text(110,335,'Keep the invoices.',78)
            text(110,515,'build/        generated files',38,True)
            text(110,595,'invoices/     10,000 records',38,True)
            text(110,795,'Same command. Two disposable copies.',34,True)
        elif t < 14.5:
            s=t-8.2
            text(110,155,'SAME DELETE / WITHOUT PREFLIGHT',28,True)
            text(110,230,"shutil.rmtree('invoices')",53,True)
            progress=ease((s-1.2)/2)
            n=int(count*(1-progress))
            text(105,370,f'{n:05,d}',170)
            text(120,590,'invoice records remain',40,True)
            d.rectangle((1040,385,1790,755),outline=fg,width=2)
            remaining=int(100*(1-progress))
            for i in range(remaining):
                x=1060+(i%10)*72;y=405+(i//10)*33
                d.rectangle((x,y,x+58,y+21),fill=fg)
            if s>3.4:text(110,800,'command executed / data removed',34,True)
        elif t < 21.4:
            s=t-14.5
            text(110,155,'SAME DELETE / WITH JUSTMYTYPE',28,True)
            text(110,230,"shutil.rmtree('invoices')",53,True)
            text(110,370,'goal  +  action  +  evidence',36,True)
            d.line((110,460,110+int(950*ease(s/1.4)),460),fill=fg,width=3)
            if s>1.4:
                d.rectangle((1130,356,1800,550),fill=fg)
                d.text((1170,385),'BLOCK',font=font(100,True),fill=bg)
                text(110,565,f'{count:,}',125)
                text(120,718,'records intact / checksum unchanged',35,True)
                ms=proof['guarded']['verdict']['latency_ms']
                text(110,820,f'preflight: {ms:.0f} ms     command did not run',31,True)
        elif t < 28:
            s=t-21.4
            text(110,155,'THE CORRECT TARGET',28,True)
            text(110,240,"shutil.rmtree('build')",55,True)
            if s>1:
                text(110,370,'PASS',105,True)
                text(110,555,'build output removed',50)
                text(110,645,'10,000 invoice records preserved',50)
                text(110,815,'Allowed work still gets done.',35,True)
        else:
            text(110,195,'JustMyType',116)
            text(110,365,"it's not you. it's your arguments.",37,True)
            text(110,495,f"held-out: {metrics['detected']}/{metrics['harmful_cases']} conflicts blocked",37,True)
            text(110,558,f"{metrics['false_blocks']} false blocks / {metrics['misses']} misses / {metrics['counts']['review']} reviews",34,True)
            text(110,680,'Linux / macOS / Windows',38)
            text(110,805,'github.com/lmtlssss/JustMyType',35,True)
        line(946)
        text(110,971,'SYNTHETIC FIXTURE REPLAY / REAL API + FILE EFFECTS',23,True)
        text(1430,971,'NOT A SECURITY BOUNDARY',23,True)
        d.line((110,1029,110+int(1700*min(t/DURATION,1)),1029),fill=fg,width=2)
        return im
    a.output.parent.mkdir(parents=True,exist_ok=True)
    if a.frames:
        a.frames.mkdir(parents=True,exist_ok=True)
        for second in [1.8,5.7,12.5,18.4,25.3,31.8]:frame(second).save(a.frames/f'frame-{second:.1f}.png')
    with tempfile.TemporaryDirectory(prefix='justmytype-film-') as temp:
        # Original sparse pulse track. No samples or third-party music.
        import array
        rate=24000
        pcm=array.array('h')
        beats=[0,3.8,8.2,11.7,14.5,16,21.4,22.5,28,31]
        for i in range(int(DURATION*rate)):
            t=i/rate;v=0
            for k,b in enumerate(beats):
                dt=t-b
                if 0<=dt<.28:
                    freq=130 if k%2==0 else 430
                    v+=.14*math.sin(2*math.pi*freq*dt)*math.exp(-dt*24)
            pcm.append(int(max(-1,min(1,v))*32767))
        wav=Path(temp)/'pulse.wav'
        with wave.open(str(wav),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate);f.writeframes(pcm.tobytes())
        cmd=['ffmpeg','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{W}x{H}','-r',str(FPS),'-i','pipe:0','-i',str(wav),'-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','128k','-movflags','+faststart','-map_metadata','-1','-metadata','title=JustMyType / field test 001','-shortest',str(a.output)]
        process=subprocess.Popen(cmd,stdin=subprocess.PIPE)
        try:
            for i in range(FPS*DURATION):process.stdin.write(frame(i/FPS).tobytes())
            process.stdin.close();code=process.wait(timeout=120)
            if code:raise RuntimeError('ffmpeg encoding failed')
        finally:
            if process.poll() is None:process.kill();process.wait()
    print(json.dumps({'video':a.output.name,'width':W,'height':H,'fps':FPS,'seconds':DURATION,'source':'measured synthetic fixture replay'}))

if __name__=='__main__':main()
