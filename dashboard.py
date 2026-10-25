"""Loopback-only Linux HTTP entry for the evaluation workbench."""
import json
import os
import secrets
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlparse
import application
import store

ROOT=store.ROOT
TOKEN=secrets.token_urlsafe(32)
PORT=int(os.environ.get('DASHBOARD_PORT','8787'))

class Handler(BaseHTTPRequestHandler):
    def respond(self,value,status=200):
        body=store.engine.dumps(value).encode()
        self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body)

    def valid_host(self):
        return self.headers.get('Host') in (f'localhost:{PORT}',f'127.0.0.1:{PORT}')

    def request_application(self,data=None):
        value,status=application.dispatch(self.command,self.path,data)
        if self.path=='/api/state' and status==200:value['token']=TOKEN
        return self.respond(value,status)

    def do_GET(self):
        if not self.valid_host():return self.respond({'error':'请通过本机地址打开界面'},403)
        route=urlparse(self.path)
        assets={'/':('index.html','text/html'),'/app.js':('app.js','application/javascript'),'/presentation.js':('presentation.js','application/javascript'),'/style.css':('style.css','text/css')}
        if route.path in assets:
            name,kind=assets[route.path];body=(ROOT/'web'/name).read_bytes()
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
        except (ValueError,UnicodeError):return self.respond({'error':'内容格式不正确或超过 4 MB'},400)
        return self.request_application(data)

if __name__=='__main__':
    os.chdir(ROOT);os.umask(0o077);store.initialize()
    ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()
