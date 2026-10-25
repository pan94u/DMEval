"""Check local API security without making model calls."""
import json
import urllib.error
import urllib.request
client=urllib.request.build_opener(urllib.request.ProxyHandler({}))
base='http://127.0.0.1:8787'
with client.open(base+'/api/state',timeout=10) as res:
    state=json.load(res)
assert state['samples'] and state['worker']
assert 'CLOUDFLARE_API_TOKEN' not in json.dumps(state)
for token in ('','invalid'):
    request=urllib.request.Request(base+'/api/tasks/create',data=b'{}',headers={'Content-Type':'application/json','X-Control-Token':token})
    try:
        client.open(request,timeout=10)
        raise AssertionError('Invalid token accepted')
    except urllib.error.HTTPError as exc:
        assert exc.code==403
try:
    client.open(base+'/api/control',timeout=10)
    raise AssertionError('Old scheduled control endpoint still available')
except urllib.error.HTTPError as exc:
    assert exc.code==404
print('PASS: state, worker availability, control token rejection, old timer API removed')
