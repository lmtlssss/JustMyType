"""Record the real Chrome UI while the real action checks run. No reconstructed frames."""
from __future__ import annotations
import argparse, hashlib, json, os, secrets, subprocess, time
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

def state(url):
    with urlopen(url.rstrip('/')+'/api/state',timeout=5) as response:return json.load(response)

def stop(process):
    if process and process.poll() is None:
        process.terminate()
        try:process.wait(timeout=8)
        except subprocess.TimeoutExpired:process.kill();process.wait()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--url',required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--rule',default='');parser.add_argument('--display',default=':103');parser.add_argument('--inspect-only',action='store_true');args=parser.parse_args()
    if urlparse(args.url).hostname not in ('127.0.0.1','localhost'):raise ValueError('Only a local demo may be recorded')
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    if Path('/tmp/.X11-unix/X'+args.display.lstrip(':')).exists():raise RuntimeError('Selected display is already owned')
    first=state(args.url)
    if first['phase']!='ready':raise RuntimeError('A ready, unexecuted plan is required')
    auth=out/'Xauthority';auth.touch(mode=0o600);subprocess.run(['xauth','-f',str(auth),'add',args.display,'.',secrets.token_hex(16)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    env=dict(os.environ,DISPLAY=args.display,XAUTHORITY=str(auth));xlog=(out/'xvfb.log').open('w');xvfb=subprocess.Popen(['Xvfb',args.display,'-screen','0','1920x1080x24','-auth',str(auth),'-nolisten','tcp'],env=env,stdout=xlog,stderr=subprocess.STDOUT);encoder=None;context=None;timeline=[];errors=[];start=time.monotonic();final=None
    def event(name,**extra):timeline.append({'seconds':round(time.monotonic()-start,3),'event':name,**extra})
    def save_json(name,value):(out/name).write_text(json.dumps(value,indent=2)+'\n')
    try:
        for _ in range(50):
            if Path('/tmp/.X11-unix/X'+args.display.lstrip(':')).exists():break
            if xvfb.poll() is not None:raise RuntimeError('Xvfb did not start')
            time.sleep(.1)
        with sync_playwright() as pw:
            context=pw.chromium.launch_persistent_context(str(out/'browser'),executable_path='/usr/bin/google-chrome',headless=False,no_viewport=True,env=env,args=['--kiosk','--window-size=1920,1080','--window-position=0,0','--force-device-scale-factor=1','--no-first-run','--disable-session-crashed-bubble','--disable-dev-shm-usage'])
            page=context.pages[0];page.on('pageerror',lambda error:errors.append(str(error)));page.goto(args.url,wait_until='domcontentloaded');page.evaluate('document.documentElement.requestFullscreen()');page.wait_for_timeout(300);page.wait_for_selector('#phase[data-phase="ready"]',timeout=15000);page.wait_for_timeout(800)
            # Kiosk is the actual Chrome UI; a screenshot verifies final geometry before recording.
            viewport=page.evaluate('({width:innerWidth,height:innerHeight,overflow:document.documentElement.scrollWidth>innerWidth})');save_json('viewport.json',viewport)
            if not (1918<=viewport['width']<=1920 and 1078<=viewport['height']<=1080) or viewport['overflow']:raise RuntimeError('Unexpected capture viewport')
            page.screenshot(path=str(out/'opening.png'))
            if args.inspect_only:
                save_json('inspection.json',{'viewport':viewport,'errors':errors,'state':'ready','applied':False});context.close();context=None;return
            flog=(out/'ffmpeg.log').open('w');video=out/'JustMyType-Refund-Desk.mp4'
            encoder=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','warning','-y','-f','x11grab','-framerate','30','-video_size','1920x1080','-draw_mouse','1','-i',args.display,'-an','-c:v','libx264','-threads','2','-preset','veryfast','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart','-map_metadata','-1',str(video)],stdin=subprocess.PIPE,stdout=flog,stderr=subprocess.STDOUT,env=env)
            start=time.monotonic();event('recording_started');page.wait_for_timeout(2200)
            if args.rule:
                page.locator('#rule').click();page.locator('#rule').press_sequentially(args.rule,delay=35);event('instruction_entered');page.wait_for_timeout(1200)
            page.locator('#apply').click();event('run_clicked');deadline=time.monotonic()+180;last=-1;midpoint=False
            while time.monotonic()<deadline:
                current=state(args.url)
                if current['processed']!=last:event('progress',processed=current['processed']);last=current['processed']
                if not midpoint and any(r['with']['status']=='held' for r in current['rows']):page.screenshot(path=str(out/'first-hold.png'));midpoint=True
                if current['phase']=='error':raise RuntimeError('The actual run failed: '+str(current['error']))
                if current['phase']=='done':final=current;event('checks_complete',summary=current['summary']);break
                page.wait_for_timeout(250)
            if final is None:raise TimeoutError('Actual checks exceeded the capture window')
            page.wait_for_selector('#phase[data-phase="done"]',timeout=10000);page.wait_for_timeout(1300)
            held=next((r for r in final['rows'] if r['with']['status']=='held'),None)
            valid=next((r for r in final['rows'] if r['with']['executed'] and r['proposed']['decision']=='refund' and r['score']['baseline_correct']),None)
            if held:
                page.locator('[data-filter="held"]').click();page.locator('[data-request-id="'+held['request_id']+'"]').click();event('held_request_opened',request_id=held['request_id']);page.wait_for_timeout(3000);page.screenshot(path=str(out/'held-detail.png'));page.locator('#evidence').click();event('evidence_opened');page.wait_for_timeout(3000);page.screenshot(path=str(out/'evidence.png'));page.locator('#close-drawer').click()
            if valid:
                page.locator('[data-filter="all"]').click();page.locator('[data-request-id="'+valid['request_id']+'"]').click();event('valid_refund_opened',request_id=valid['request_id']);page.wait_for_timeout(3000)
            if held:
                page.locator('[data-filter="held"]').click();page.locator('[data-request-id="'+held['request_id']+'"]').click()
            page.wait_for_timeout(2600);page.screenshot(path=str(out/'final.png'));event('recording_finished');save_json('actual-state.json',final)
            encoder.stdin.write(b'q\n');encoder.stdin.flush();encoder.communicate(timeout=30)
            if encoder.returncode:raise RuntimeError('Video encoder failed')
            context.close();context=None
            probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height,r_frame_rate,nb_frames:format=duration,size','-of','json',str(video)]))
            save_json('receipt.json',{'kind':'actual_live_browser_recording','video_sha256':hashlib.sha256(video.read_bytes()).hexdigest(),'video':probe,'browser_viewport':viewport,'events':timeline,'page_errors':errors,'shared_proposals':True,'synthetic':True,'new_rule':args.rule,'summary':final['summary'],'editing':'none','audio':False})
            print(json.dumps({'video':str(video),'receipt':str(out/'receipt.json'),'summary':final['summary']}),flush=True)
    except Exception as error:
        save_json('capture-failure.json',{'error':str(error),'events':timeline,'page_errors':errors});raise
    finally:
        if context:
            try:context.close()
            except Exception:pass
        if encoder and encoder.poll() is None:
            try:encoder.stdin.write(b'q\n');encoder.stdin.flush();encoder.communicate(timeout=15)
            except Exception:stop(encoder)
        stop(xvfb);xlog.close()
        if auth.exists():auth.unlink()
if __name__=='__main__':main()
