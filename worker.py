"""Only runs explicitly queued tasks. No timed evaluations."""
import os
import signal
import subprocess
import sys
import time
import store

STOP = False
def stop(*_):
    global STOP
    STOP = True

def execute(tid):
    task = store.task_detail(tid)
    folder = store.ROOT/'runs/tasks'
    folder.mkdir(parents=True,exist_ok=True)
    dataset = folder/(tid+'.jsonl')
    dataset.write_text('\n'.join(store.engine.dumps(s['case']) for s in task['samples'])+'\n',encoding='utf-8')
    cfg = task['config']
    with (folder/(tid+'.log')).open('a') as log:
        proc = subprocess.Popen([sys.executable,str(store.ROOT/'eval.py'),'run','--dataset',str(dataset),'--db',str(store.DB),'--provider',cfg['provider'],'--models',','.join(cfg['models']),'--repeats',str(cfg['repeats']),'--run-id',tid],cwd=store.ROOT,stdout=log,stderr=log)
        cancelled = False
        while proc.poll() is None:
            with store.connect() as db:
                status = db.execute('SELECT status FROM tasks WHERE id=?',(tid,)).fetchone()[0]
            if STOP or status=='cancelling':
                cancelled = status=='cancelling'
                proc.terminate()
                try:
                    proc.wait(timeout=50)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                break
            time.sleep(.3)
    current = store.task_detail(tid)
    if cancelled or current['status']=='cancelling':
        status,error = 'cancelled',''
    elif STOP:
        status,error = 'queued','服务重启后继续执行'
    elif current['done']!=current['total']:
        status,error = 'failed','执行未完成，请检查凭证或重建任务后重试'
    elif current['errors']:
        status,error = ('failed' if current['errors']==current['total'] else 'partial_failed'),'部分请求失败，请查看逐样本结果'
    elif proc.returncode:
        status,error = 'failed','执行进程异常退出'
    else:
        status,error = 'completed',''
    with store.connect() as db:
        db.execute('UPDATE tasks SET status=?,error=?,updated=? WHERE id=?',(status,error,time.time(),tid))

def main():
    os.chdir(store.ROOT)
    os.umask(0o077)
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    store.initialize()
    with store.connect() as db:
        db.execute("UPDATE tasks SET status='queued' WHERE status='running'")
        db.execute("UPDATE tasks SET status='cancelled' WHERE status='cancelling'")
    while not STOP:
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT id FROM tasks WHERE status='queued' AND archived=0 ORDER BY created LIMIT 1").fetchone()
            if row:
                db.execute("UPDATE tasks SET status='running',updated=? WHERE id=?",(time.time(),row[0]))
        if row:
            try:
                execute(row[0])
            except Exception:
                with store.connect() as db:
                    db.execute("UPDATE tasks SET status='failed',error='任务执行异常，请让我检查后台',updated=? WHERE id=?",(time.time(),row[0]))
        else:
            time.sleep(1)

if __name__=='__main__':
    main()
