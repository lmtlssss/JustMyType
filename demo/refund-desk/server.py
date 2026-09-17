"""Loopback-only live refund demo with an immutable prepared plan."""
from __future__ import annotations
import argparse
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import urlparse
import bench
HERE=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--plan',type=Path,required=True)
    args=parser.parse_args()
    state=bench.ready_state(args.plan)
    lock=threading.Lock()
    started=False
    def update(value):
        nonlocal state
        with lock: state=value
    def work(rule):
        try: bench.apply_plan(args.plan,args.run_dir,rule,callback=update)
        except Exception as error:
            with lock: state.update(phase='error',error=type(error).__name__+': '+str(error))
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def send(self,body,status=200,mime='application/json; charset=utf-8'):
            if not isinstance(body,bytes): body=json.dumps(body,ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers()
            self.wfile.write(body)
        def valid_host(self):
            return self.headers.get('Host') in {f'127.0.0.1:{args.port}',f'localhost:{args.port}'}
        def do_GET(self):
            if not self.valid_host(): return self.send({'error':'Invalid host'},403)
            path=urlparse(self.path).path
            if path in {'/api/state','/api/evidence'}:
                with lock: value=copy.deepcopy(state)
                return self.send(value)
            if path=='/api/policy': return self.send(state['policy'].encode(),mime='text/plain; charset=utf-8')
            files={'/':('index.html','text/html; charset=utf-8'),'/index.html':('index.html','text/html; charset=utf-8'),'/fixture.json':('fixture.json','application/json'),'/policy.txt':('policy.txt','text/plain; charset=utf-8')}
            if path in files:
                name,mime=files[path]
                return self.send((HERE/name).read_bytes(),mime=mime)
            return self.send({'error':'Not found'},404)
        def do_POST(self):
            nonlocal started
            if not self.valid_host(): return self.send({'error':'Invalid host'},403)
            origin=self.headers.get('Origin')
            if origin and origin not in {f'http://127.0.0.1:{args.port}',f'http://localhost:{args.port}'}:
                return self.send({'error':'Cross-origin writes are disabled'},403)
            if self.path!='/api/apply': return self.send({'error':'Prepare a plan with the CLI before starting this viewer'},404)
            try:
                length=int(self.headers.get('Content-Length','0'))
                if length<2 or length>4096: raise ValueError('Invalid request size')
                body=json.loads(self.rfile.read(length));rule=body.get('extra_rule','')
                if not isinstance(rule,str) or rule not in {'',bench.CAP_RULE}: raise ValueError('Use the original policy or the displayed $100 review instruction')
                with lock:
                    if started or state['phase']!='ready': return self.send({'error':'This run has already started'},409)
                    started=True
                    state.update(phase='checking',extra_rule=rule)
                threading.Thread(target=work,args=(rule,),daemon=True).start()
                return self.send({'started':True},202)
            except (ValueError,TypeError,json.JSONDecodeError) as error: return self.send({'error':str(error)},400)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'Refund desk listening on 127.0.0.1:{args.port}',flush=True)
    try: server.serve_forever()
    finally: server.server_close()
if __name__=='__main__': main()
