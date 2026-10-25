"""End-to-end single and batch task checks. --live makes 10 paid API calls."""
import argparse
import json
import time
import urllib.request

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--live',action='store_true')
args=parser.parse_args()
base='http://127.0.0.1:8787'
client=urllib.request.build_opener(urllib.request.ProxyHandler({}))

def api(path,data=None):
    req=urllib.request.Request(base+path,data=None if data is None else json.dumps(data).encode(),headers={'Content-Type':'application/json','X-Control-Token':token})
    with client.open(req,timeout=15) as res:
        return json.load(res)

token=''
state=api('/api/state')
token=state['token']
provider='cloudflare' if args.live else 'mock'
ids=[]
for name,samples in [('示例 · 单样本测试',['route-zh']),('示例 · 批量模型对比',['route-zh','route-en','severity','injection'])]:
    created=api('/api/tasks/create',dict(name=name if args.live else '检查 · '+name,sample_ids=samples,models=['clef','clef-flash'],provider=provider,start=True))
    ids.append(created['id'])
deadline=time.monotonic()+120
while time.monotonic()<deadline:
    tasks=[api('/api/task?id='+tid) for tid in ids]
    if all(t['status'] in ('completed','partial_failed','failed','cancelled') for t in tasks):
        break
    time.sleep(1)
else:
    raise AssertionError('Tasks did not finish')
for t in tasks:
    assert t['status']=='completed',(t['name'],t['status'],t['error'])
    assert t['done']==t['total'] and t['errors']==0
    print(json.dumps(dict(id=t['id'],name=t['name'],status=t['status'],requests=t['done'],samples=t['sample_count']),ensure_ascii=False))
    if not args.live:
        api('/api/tasks/action',{'id':t['id'],'action':'archive'})
print('PASS: single and batch task execution and saved results')
