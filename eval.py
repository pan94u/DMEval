"""Resumable decision evaluation. Python 3.11+, standard library only."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import signal
import sqlite3
import statistics
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = '1'
STOP = threading.Event()

def dumps(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, allow_nan=False)

def digest(x):
    return hashlib.sha256(dumps(x).encode()).hexdigest()

def options(q):
    if q['type'] == 'noul':
        return ['false', 'true']
    if q['type'] == 'choice':
        return list(q['criteria'])
    if q['type'] == 'score':
        return [str(i) for i in range(len(q['criteria']))]
    raise ValueError('Unknown question type')

def load_cases(path):
    cases = [json.loads(s) for s in Path(path).read_text(encoding='utf-8').splitlines() if s.strip()]
    return validate_cases(cases)

def validate_cases(cases):
    if not isinstance(cases,list):
        raise ValueError('Dataset must be a list')
    ids = set()
    for c in cases:
        if not isinstance(c['id'],str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',c['id']) or c['id'] in ids:
            raise ValueError('Case IDs must be unique strings')
        ids.add(c['id'])
        if 'state' not in c or not 1 <= len(c['questions']) <= 64:
            raise ValueError('state and 1..64 questions required')
        if set(c['expected']) != set(c['questions']):
            raise ValueError('Every question needs an expected label')
        for key, q in c['questions'].items():
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',key):
                raise ValueError('Invalid question ID')
            if q['type']=='choice' and (not isinstance(q.get('criteria'),dict) or len(q['criteria'])<2):
                raise ValueError('At least two named options required')
            if q['type']=='score' and (not isinstance(q.get('criteria'),list) or len(q['criteria'])<2):
                raise ValueError('At least two score levels required')
            opts = options(q)
            y = c['expected'][key]
            if not opts or (q['type'] == 'noul' and type(y) is not bool):
                raise ValueError('Invalid criteria/boolean label')
            if q['type'] == 'choice' and y not in opts:
                raise ValueError('Expected choice outside criteria')
            if q['type'] == 'score' and (type(y) not in (int, float) or not math.isfinite(y) or not 0 <= y <= len(opts)-1):
                raise ValueError('Expected score outside rubric')
    if not cases:
        raise ValueError('Dataset is empty')
    return cases

def evaluate(case, response):
    rows = []
    for key, q in case['questions'].items():
        a = response['answers'][key]
        opts = options(q)
        y = case['expected'][key]
        if q['type'] == 'noul':
            p = float(a['noul'])
            probs = {'false': 1-p, 'true': p}
            target = str(y).lower()
        else:
            probs = {str(k): float(v) for k, v in a['probabilities'].items()}
            target = str(y)
        if set(probs) != set(opts) or any(not math.isfinite(p) or not 0 <= p <= 1 for p in probs.values()) or abs(sum(probs.values())-1) > .002:
            raise ValueError('Invalid probability distribution')
        pred = ('true' if probs['true']>=.5 else 'false') if q['type']=='noul' else max(opts,key=probs.get)
        row = {'question': key, 'type': q['type'], 'expected': y, 'prediction': pred}
        if q['type'] == 'score':
            score = sum(int(k)*p for k, p in probs.items())
            row.update(mae=abs(score-y), score=score)
        else:
            row.update(correct=int(pred == target), confidence=probs[pred],
                       brier=sum((p-int(k == target))**2 for k, p in probs.items()),
                       log_loss=-math.log(max(probs[target], 1e-15)))
        rows.append(row)
    return rows

def mock_response(case):
    # Deliberately label-blind uniform baseline; never use gold labels for inference.
    answers = {}
    for key, q in case['questions'].items():
        opts = options(q)
        answers[key] = {'noul': .5} if q['type'] == 'noul' else {'probabilities': {k: 1/len(opts) for k in opts}}
    return {'answers': answers, 'usage': {'input_tokens': 0}}

def request_json(url, token, body=None, retries=3, timeout=45):
    for attempt in range(retries+1):
        req = urllib.request.Request(url, data=None if body is None else dumps(body).encode(),
                                     headers={'Authorization': 'Bearer '+token, 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                data = json.load(res)
            if data.get('success') is False:
                raise RuntimeError('API returned success=false')
            return data.get('result', data)
        except urllib.error.HTTPError as exc:
            status = exc.code
            if status not in (429, 500, 502, 503, 504) or attempt == retries:
                raise RuntimeError(f'API HTTP {status}') from None
            delay = exc.headers.get('Retry-After', '')
            delay = min(float(delay), 120) if delay.isdigit() else 2**attempt + random.random()
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries:
                raise RuntimeError('API network error or timeout') from None
            delay = 2**attempt + random.random()
        if STOP.wait(delay):
            raise RuntimeError('Interrupted')

def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, created REAL, spec TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS results (run TEXT, model TEXT, case_id TEXT, repeat INTEGER, status TEXT, latency REAL, payload TEXT, PRIMARY KEY(run,model,case_id,repeat))')
    return db

def summary(db, run):
    out = {}
    for model, status, latency, payload in db.execute('SELECT model,status,latency,payload FROM results WHERE run=?', (run,)):
        s = out.setdefault(model, {'requests': 0, 'errors': 0, 'latencies': [], 'rows': [], 'input_tokens': 0})
        s['requests'] += 1
        s['latencies'].append(latency)
        if status != 'ok':
            s['errors'] += 1
        else:
            p = json.loads(payload)
            s['rows'].extend(p['metrics'])
            s['input_tokens'] += p['response'].get('usage', {}).get('input_tokens', 0) or 0
    for s in out.values():
        lat = sorted(s.pop('latencies'))
        rows = s.pop('rows')
        s['p50_ms'] = statistics.median(lat)
        s['p95_ms'] = lat[max(0, math.ceil(.95*len(lat))-1)]
        s['error_rate'] = s['errors']/s['requests']
        for name in ('correct', 'brier', 'log_loss', 'mae'):
            vals = [r[name] for r in rows if name in r]
            s['accuracy' if name == 'correct' else name] = statistics.mean(vals) if vals else None
        classified = [r for r in rows if 'correct' in r]
        s['ece_10_bins'] = sum(abs(sum(r['confidence']-r['correct'] for r in classified if min(9,int(r['confidence']*10)) == b)) for b in range(10))/len(classified) if classified else None
        s['scored_questions'] = len(rows)
    return out

def run_once(args):
    import fcntl
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    with open(str(args.db)+'.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another evaluation is running') from None
        return _run_once(args)

def _run_once(args):
    cases = load_cases(args.dataset)
    models = args.models.split(',')
    spec = {'version': VERSION, 'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'dataset': digest(cases), 'models': models, 'provider': args.provider,
            'endpoint': args.endpoint, 'account': os.environ.get('CLOUDFLARE_ACCOUNT_ID', ''), 'repeats': args.repeats}
    run = args.run_id or digest(spec)[:20]
    db = connect(args.db)
    old = db.execute('SELECT spec FROM runs WHERE id=?', (run,)).fetchone()
    if old and old[0] != dumps(spec):
        raise ValueError('Run ID already belongs to different inputs/configuration')
    token = os.environ.get('CLOUDFLARE_API_TOKEN', '') if args.provider == 'cloudflare' else os.environ.get('DECISION_API_TOKEN', '')
    account = os.environ.get('CLOUDFLARE_ACCOUNT_ID', '')
    if args.provider == 'cloudflare' and (not token or not account):
        raise ValueError('Set CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID')
    if args.provider == 'systemone' and not args.endpoint:
        raise ValueError('--endpoint required for systemone')
    with db:
        db.execute('INSERT OR IGNORE INTO runs VALUES (?,?,?)', (run, time.time(), dumps(spec)))
    for model in models:
        for c in cases:
            for repeat in range(args.repeats):
                if STOP.is_set():
                    break
                key = (run, model, c['id'], repeat)
                old = db.execute('SELECT status FROM results WHERE run=? AND model=? AND case_id=? AND repeat=?', key).fetchone()
                if old and (old[0] == 'ok' or not args.retry_errors):
                    continue
                started = time.monotonic()
                try:
                    if args.provider == 'mock':
                        response = mock_response(c)
                    else:
                        url = f'https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/@cf/cloudflare/{model}' if args.provider == 'cloudflare' else args.endpoint
                        body = {k: c[k] for k in ('state', 'questions', 'images', 'videos') if k in c}
                        body['model'] = model
                        response = request_json(url, token, body)
                    payload = {'metrics': evaluate(c, response), 'response': response}
                    status = 'ok'
                except Exception as exc:
                    # No exception text, request headers, or remote error body in storage.
                    payload = {'error_type': type(exc).__name__}
                    status = 'error'
                elapsed = (time.monotonic()-started)*1000
                with db:
                    db.execute('INSERT OR REPLACE INTO results VALUES (?,?,?,?,?,?,?)', (*key,status,elapsed,dumps(payload)))
                print(dumps({'run':run,'model':model,'case':c['id'],'repeat':repeat,'status':status}), flush=True)
                STOP.wait(args.delay)
    result = {'run': run, 'summary': summary(db, run)}
    print(dumps(result), flush=True)
    if args.output:
        Path(args.output).write_text(dumps(result)+'\n', encoding='utf-8')
    db.close()
    return result

def serve(args):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != '/':
                self.send_error(404)
                return
            with connect(args.db) as db:
                runs = [{'id': r[0], 'created': r[1], 'spec':json.loads(r[2]), 'summary':summary(db,r[0])} for r in db.execute('SELECT * FROM runs ORDER BY created DESC LIMIT 50').fetchall()]
            body = dumps(runs).encode()
            self.send_response(200)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.timeout = 1
    print(f'History: http://127.0.0.1:{args.port}', flush=True)
    while not STOP.is_set():
        server.handle_request()
    server.server_close()

def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    for cmd in ('run', 'watch'):
        s = sub.add_parser(cmd)
        s.add_argument('--dataset', default='data/smoke.jsonl')
        s.add_argument('--provider', choices=['mock','cloudflare','systemone'], default='mock')
        s.add_argument('--models', default='clef,clef-flash')
        s.add_argument('--endpoint', default='')
        s.add_argument('--run-id')
        s.add_argument('--fresh', action='store_true')
        s.add_argument('--repeats', type=int, default=1)
        s.add_argument('--delay', type=float, default=.25)
        s.add_argument('--retry-errors', action='store_true')
        s.add_argument('--output')
        s.add_argument('--db', default='runs/evaluations.sqlite3')
        if cmd == 'watch':
            s.add_argument('--interval', type=float, default=3600)
    s = sub.add_parser('serve')
    s.add_argument('--db', default='runs/evaluations.sqlite3')
    s.add_argument('--port', type=int, default=8787)
    a = p.parse_args()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: STOP.set())
    if a.command == 'serve':
        serve(a)
        return
    if a.repeats < 1 or a.delay < 0:
        p.error('repeats must be positive and delay nonnegative')
    if a.command == 'watch':
        if a.interval < 1 or a.run_id:
            p.error('watch requires interval >= 1 and generates its own run IDs')
        while not STOP.is_set():
            a.run_id = f'watch-{time.time_ns()}'
            try:
                run_once(a)
            except Exception as exc:
                print(dumps({'watch_error':type(exc).__name__}), flush=True)
            STOP.wait(a.interval)
    else:
        if a.fresh:
            a.run_id = f'manual-{time.time_ns()}'
        result = run_once(a)
        if any(s['errors'] for s in result['summary'].values()):
            raise SystemExit(2)

if __name__ == '__main__':
    main()
