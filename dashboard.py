"""Local sample library, task management, and saved decision results."""
import json
import os
import secrets
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import store

ROOT,DB = store.ROOT,store.DB
TOKEN = secrets.token_urlsafe(32)
PORT = int(os.environ.get('DASHBOARD_PORT','8787'))

class Handler(BaseHTTPRequestHandler):
    def respond(self,value,status=200):
        body = store.engine.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def valid_host(self):
        return self.headers.get('Host') in (f'localhost:{PORT}',f'127.0.0.1:{PORT}')

    def do_GET(self):
        if not self.valid_host():
            return self.respond({'error':'请通过本机地址打开界面'},403)
        route = urlparse(self.path)
        if route.path in ('/','/app.js','/style.css'):
            name,ctype = {'/':('index.html','text/html'),'/app.js':('app.js','application/javascript'),'/style.css':('style.css','text/css')}[route.path]
            body = (ROOT/'web'/name).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type',ctype+'; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Frame-Options','DENY')
            self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers()
            return self.wfile.write(body)
        try:
            if route.path=='/api/state':
                worker = subprocess.run(['systemctl','--user','is-active','decision-task-worker.service'],capture_output=True,text=True,timeout=5)
                return self.respond({'token':TOKEN,'samples':store.samples(),'tasks':store.tasks(),'worker':worker.returncode==0})
            if route.path=='/api/task':
                return self.respond(store.task_detail(parse_qs(route.query).get('id',[''])[0]))
            if route.path=='/api/history':
                return self.respond(store.historical_runs())
            if route.path=='/api/history-detail':
                rid = parse_qs(route.query).get('id',[''])[0]
                with store.connect() as db:
                    return self.respond([dict(model=m,case_id=c,repeat=r,status=s,latency=lat,**json.loads(p)) for m,c,r,s,lat,p in db.execute('SELECT model,case_id,repeat,status,latency,payload FROM results WHERE run=? ORDER BY model,case_id,repeat',(rid,))])
            return self.respond({'error':'页面不存在'},404)
        except ValueError as exc:
            return self.respond({'error':str(exc)},400)
        except Exception:
            return self.respond({'error':'读取失败，请刷新或让我检查后台'},500)

    def do_POST(self):
        if not self.valid_host() or self.headers.get('X-Control-Token')!=TOKEN:
            return self.respond({'error':'请刷新页面后重试'},403)
        if self.headers.get('Origin') not in (None,f'http://localhost:{PORT}',f'http://127.0.0.1:{PORT}'):
            return self.respond({'error':'请求来源不正确'},403)
        try:
            length = int(self.headers.get('Content-Length','0'))
            if not 0<length<=4*1024*1024:
                raise ValueError('内容为空或超过 4 MB')
            data = json.loads(self.rfile.read(length))
            if self.path=='/api/samples/save':
                return self.respond({'id':store.save_sample(data),'message':'样本已保存'})
            if self.path=='/api/samples/delete':
                store.archive_sample(data['id'])
                return self.respond({'message':'样本已移出列表，已有任务不受影响'})
            if self.path=='/api/samples/import':
                count = store.import_samples(data['samples'])
                return self.respond({'message':f'已导入 {count} 个样本'})
            if self.path=='/api/tasks/create':
                return self.respond({'id':store.create_task(data),'message':'任务已创建'})
            if self.path=='/api/tasks/action':
                action = data['action']
                messages = {'start':'任务已加入队列','cancel':'正在取消任务','archive':'任务已移出列表','clone':'已创建任务副本，可再次运行'}
                if action not in messages:
                    raise ValueError('未知操作')
                return self.respond({'id':store.task_action(data['id'],action),'message':messages[action]})
            return self.respond({'error':'操作不存在'},404)
        except ValueError as exc:
            return self.respond({'error':str(exc)},400)
        except (KeyError,TypeError,AttributeError):
            return self.respond({'error':'内容格式不正确，请检查问题、选项和标准答案'},400)
        except Exception:
            return self.respond({'error':'操作未完成，请稍后重试或让我检查后台'},500)

if __name__=='__main__':
    os.chdir(ROOT)
    os.umask(0o077)
    store.initialize()
    ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()
