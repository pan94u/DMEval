"""Loopback-only Windows entry; storage and task execution remain inside WSL."""
import argparse
import json
from pathlib import Path
import secrets
import subprocess
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlparse

TOKEN=secrets.token_urlsafe(32)
ROOT=Path(__file__).resolve().parent
PORT=8787
DISTRIBUTION='Ubuntu-24.04'
PROJECT='/home/szq43/code/decision-model-eval'

class Handler(BaseHTTPRequestHandler):
    def respond(self,value,status=200):
        body=json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers();self.wfile.write(body)

    def valid_host(self):
        return self.headers.get('Host') in (f'localhost:{PORT}',f'127.0.0.1:{PORT}')

    def request_application(self,data=None):
        try:
            result=subprocess.run(['wsl.exe','-d',DISTRIBUTION,'--cd',PROJECT,'--exec','python3','bridge.py'],
                input=json.dumps({'method':self.command,'path':self.path,'data':data},ensure_ascii=False),
                capture_output=True,encoding='utf-8',timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:raise RuntimeError('Bridge unavailable')
            reply=json.loads(result.stdout)
            if self.path=='/api/state' and reply['status']==200:
                reply['value']['token']=TOKEN
            return self.respond(reply['value'],reply['status'])
        except Exception:
            return self.respond({'error':'任务服务暂时未连接，请稍后刷新'},503)

    def do_GET(self):
        if not self.valid_host():return self.respond({'error':'请使用本机地址'},403)
        path=urlparse(self.path).path
        assets={'/':('index.html','text/html'),'/app.js':('app.js','application/javascript'),'/presentation.js':('presentation.js','application/javascript'),'/style.css':('style.css','text/css')}
        if path in assets:
            filename,kind=assets[path]
            try:body=(ROOT/'web'/filename).read_bytes()
            except OSError:return self.respond({'error':'界面文件暂时不可读，请稍后刷新'},503)
            self.send_response(200);self.send_header('Content-Type',kind+'; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Frame-Options','DENY');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body)
            return
        return self.request_application()

    def do_POST(self):
        if not self.valid_host() or self.headers.get('X-Control-Token')!=TOKEN or self.headers.get('Origin') not in (None,f'http://localhost:{PORT}',f'http://127.0.0.1:{PORT}'):
            return self.respond({'error':'请刷新页面后重试'},403)
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=4*1024*1024:raise ValueError('body size')
            data=json.loads(self.rfile.read(length))
        except (ValueError,UnicodeError):
            return self.respond({'error':'提交内容不正确或超过 4 MB'},400)
        return self.request_application(data)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8787)
    parser.add_argument('--distribution',default=DISTRIBUTION)
    parser.add_argument('--project',default=PROJECT)
    args=parser.parse_args();PORT=args.port;DISTRIBUTION=args.distribution;PROJECT=args.project
    print(f'Workbench: http://localhost:{PORT}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()
