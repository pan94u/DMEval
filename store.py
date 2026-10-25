"""Versioned sample library and explicit, durable evaluation tasks."""
import json
import math
import sqlite3
from pathlib import Path
import time
import uuid
import eval as engine

ROOT = Path(__file__).resolve().parent
DB = ROOT/'runs/evaluations.sqlite3'
TERMINAL = ('completed','partial_failed','failed','cancelled')

def connect():
    db = engine.connect(DB)
    db.row_factory = sqlite3.Row
    return db

def initialize():
    with connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS samples (id TEXT PRIMARY KEY,title TEXT,category TEXT,body TEXT,revision INTEGER,updated REAL,archived INTEGER DEFAULT 0)')
        db.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY,name TEXT,status TEXT,created REAL,updated REAL,config TEXT,snapshot TEXT,error TEXT,archived INTEGER DEFAULT 0)')
        db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY,value TEXT)')
        db.execute('CREATE TABLE IF NOT EXISTS task_policies (task TEXT,model TEXT,rule_id TEXT,threshold REAL,updated REAL,PRIMARY KEY(task,model,rule_id))')
        if not db.execute("SELECT 1 FROM metadata WHERE key='samples_migrated'").fetchone():
            names = {'route-zh':'中文客服路由','route-en':'英文账单路由','severity':'生产故障等级','injection':'指令干扰识别'}
            for c in engine.load_cases(ROOT/'data/smoke.jsonl'):
                db.execute('INSERT OR IGNORE INTO samples VALUES (?,?,?,?,?,?,0)',(c['id'],names.get(c['id'],c['id']),'示例样本',engine.dumps(c),1,time.time()))
            db.execute("INSERT INTO metadata VALUES ('samples_migrated','1')")

def sample(row):
    return {'id':row['id'],'title':row['title'],'category':row['category'],'case':json.loads(row['body']),'revision':row['revision'],'updated':row['updated']}

def samples():
    with connect() as db:
        return [sample(r) for r in db.execute('SELECT * FROM samples WHERE archived=0 ORDER BY updated DESC,id')]

def save_sample(data):
    c = data['case']
    engine.validate_cases([c])
    title = str(data.get('title','')).strip()
    category = str(data.get('category','')).strip()
    if not title or len(title)>100 or len(category)>60:
        raise ValueError('请填写样本名称（最多 100 字），分组最多 60 字')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        old = db.execute('SELECT * FROM samples WHERE id=?',(c['id'],)).fetchone()
        if old:
            if data.get('revision')!=old['revision'] or old['archived']:
                raise ValueError('样本已更新或编号已使用，请刷新后重试')
            db.execute('UPDATE samples SET title=?,category=?,body=?,revision=revision+1,updated=? WHERE id=?',(title,category,engine.dumps(c),time.time(),c['id']))
        else:
            db.execute('INSERT INTO samples VALUES (?,?,?,?,?,?,0)',(c['id'],title,category,engine.dumps(c),1,time.time()))
    return c['id']

def archive_sample(sid):
    with connect() as db:
        if not db.execute('UPDATE samples SET archived=1,updated=? WHERE id=? AND archived=0',(time.time(),sid)).rowcount:
            raise ValueError('样本不存在')

def import_samples(rows):
    if not isinstance(rows,list) or not 1<=len(rows)<=1000:
        raise ValueError('一次可导入 1–1000 个样本')
    engine.validate_cases(rows)
    with connect() as db:
        ids = {r[0] for r in db.execute('SELECT id FROM samples')}
        if any(c['id'] in ids for c in rows):
            raise ValueError('导入编号与已有样本重复，请先修改编号；没有样本被导入')
        for c in rows:
            db.execute('INSERT INTO samples VALUES (?,?,?,?,?,?,0)',(c['id'],str(c.get('title',c['id']))[:100],str(c.get('category','导入样本'))[:60],engine.dumps(c),1,time.time()))
    return len(rows)

def create_task(data,snapshot=None):
    name = str(data.get('name','')).strip()
    models = data.get('models')
    repeats = data.get('repeats',1)
    provider = data.get('provider','cloudflare')
    if not name or len(name)>100:
        raise ValueError('请填写任务名称（最多 100 字）')
    if not isinstance(models,list) or not models or len(models)!=len(set(models)) or any(m not in ('clef','clef-flash') for m in models):
        raise ValueError('请选择 Clef 或 Clef-flash')
    if type(repeats) is not int or not 1<=repeats<=5 or provider not in ('cloudflare','mock'):
        raise ValueError('每样本重复次数应为 1–5')
    if snapshot is None:
        ids = data.get('sample_ids',[])
        if not isinstance(ids,list) or not ids or len(ids)!=len(set(ids)) or len(ids)>1000:
            raise ValueError('请选择 1–1000 个样本')
        library = {c['id']:c for c in samples()}
        if any(sid not in library for sid in ids):
            raise ValueError('部分样本已删除，请重新选择')
        snapshot = [library[sid] for sid in ids]
    engine.validate_cases([s['case'] for s in snapshot])
    tid = 'task-'+uuid.uuid4().hex[:16]
    tolerance=data.get('score_tolerance',.5)
    if type(tolerance) not in (int,float) or not math.isfinite(tolerance) or not 0<=tolerance<=100:
        raise ValueError('评分允许误差必须是 0–100 之间的数值')
    config = {'models':models,'repeats':repeats,'provider':provider,'dataset':engine.digest(snapshot),'score_tolerance':tolerance}
    status = 'queued' if data.get('start') else 'draft'
    with connect() as db:
        db.execute('INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,0)',(tid,name,status,time.time(),time.time(),engine.dumps(config),engine.dumps(snapshot),''))
    return tid

def task(row,db):
    t = dict(row)
    t['config'] = json.loads(t['config'])
    snap = json.loads(t.pop('snapshot'))
    t['sample_count'] = len(snap)
    t['total'] = len(snap)*len(t['config']['models'])*t['config']['repeats']
    t['done'] = db.execute('SELECT COUNT(*) FROM results WHERE run=?',(t['id'],)).fetchone()[0]
    t['errors'] = db.execute("SELECT COUNT(*) FROM results WHERE run=? AND status!='ok'",(t['id'],)).fetchone()[0]
    return t

def tasks():
    with connect() as db:
        return [task(r,db) for r in db.execute('SELECT * FROM tasks WHERE archived=0 ORDER BY created DESC').fetchall()]

def task_detail(tid):
    with connect() as db:
        row = db.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone()
        if not row:
            raise ValueError('任务不存在')
        t = task(row,db)
        t['samples'] = json.loads(row['snapshot'])
        for sample in t['samples']:
            sample['question_rules']={key:rule_id(key,q) for key,q in sample['case']['questions'].items() if q['type']=='noul'}
        t['decision_policy']=[dict(r) for r in db.execute('SELECT model,rule_id,threshold,updated FROM task_policies WHERE task=?',(tid,))]
        t['summary'] = engine.summary(db,tid)
        t['results'] = [dict(model=m,case_id=c,repeat=r,status=s,latency=lat,**json.loads(p)) for m,c,r,s,lat,p in db.execute('SELECT model,case_id,repeat,status,latency,payload FROM results WHERE run=? ORDER BY case_id,model,repeat',(tid,))]
        return t

def task_action(tid,action):
    with connect() as db:
        row = db.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone()
        if not row:
            raise ValueError('任务不存在')
        if action=='start' and row['status']=='draft':
            db.execute("UPDATE tasks SET status='queued',updated=? WHERE id=?",(time.time(),tid))
        elif action=='cancel' and row['status'] in ('queued','running'):
            db.execute("UPDATE tasks SET status=?,updated=? WHERE id=?",('cancelling' if row['status']=='running' else 'cancelled',time.time(),tid))
        elif action=='archive' and row['status'] in ('draft',)+TERMINAL:
            db.execute('UPDATE tasks SET archived=1 WHERE id=?',(tid,))
        elif action=='clone':
            config = json.loads(row['config'])
            new_id=create_task(dict(config,name=row['name']+' · 副本'),json.loads(row['snapshot']))
            with connect() as target:
                target.execute('INSERT INTO task_policies SELECT ?,model,rule_id,threshold,? FROM task_policies WHERE task=?',(new_id,time.time(),tid))
            return new_id
        else:
            raise ValueError('任务状态已变化，请刷新后重试')
    return tid

def rule_id(key,question):
    return engine.digest({'question':key,'instructions':question.get('instructions') or '', 'criteria':question.get('criteria') or {}})

def save_policy(tid,model,rule,threshold):
    if type(threshold) not in (int,float) or not math.isfinite(threshold) or not 0<=threshold<=1:
        raise ValueError('判断阈值必须在 0%–100% 之间')
    task=task_detail(tid)
    rules={rid for s in task['samples'] for rid in s['question_rules'].values()}
    if model not in task['config']['models'] or rule not in rules:
        raise ValueError('请选择本任务中的模型和是／否问题')
    with connect() as db:
        db.execute('INSERT INTO task_policies VALUES (?,?,?,?,?) ON CONFLICT(task,model,rule_id) DO UPDATE SET threshold=excluded.threshold,updated=excluded.updated',(tid,model,rule,threshold,time.time()))

def remove_unassigned_records():
    """Remove obsolete, pre-task eval records after the user requested their removal."""
    with connect() as db:
        db.execute('DELETE FROM results WHERE run NOT IN (SELECT id FROM tasks)')
        count=db.execute('DELETE FROM runs WHERE id NOT IN (SELECT id FROM tasks)').rowcount
    return count
