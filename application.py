"""Application operations shared by the Linux HTTP and Windows local entry."""
import subprocess
from urllib.parse import urlparse,parse_qs
import store

def dispatch(method,path,data=None):
    route=urlparse(path)
    try:
        if method=='GET':
            if route.path=='/api/state':
                worker=subprocess.run(['systemctl','--user','is-active','decision-task-worker.service'],capture_output=True,text=True,timeout=5)
                return {'samples':store.samples(),'tasks':store.tasks(),'worker':worker.returncode==0},200
            if route.path=='/api/task':
                return store.task_detail(parse_qs(route.query).get('id',[''])[0]),200
        if method=='POST':
            if path=='/api/samples/save':
                return {'id':store.save_sample(data),'message':'样本已保存'},200
            if path=='/api/samples/delete':
                store.archive_sample(data['id'])
                return {'message':'样本已移出列表，已有任务不受影响'},200
            if path=='/api/samples/import':
                count=store.import_samples(data['samples'])
                return {'message':f'已导入 {count} 个样本'},200
            if path=='/api/tasks/create':
                return {'id':store.create_task(data),'message':'任务已创建'},200
            if path=='/api/tasks/policy':
                store.save_policy(data['id'],data['model'],data['rule_id'],data['threshold'])
                return {'message':'判断规则已保存到此任务，原始响应不变'},200
            if path=='/api/tasks/action':
                messages={'start':'任务已加入队列','cancel':'正在取消任务','archive':'任务已移出列表','clone':'已创建任务副本，可再次运行'}
                action=data['action']
                if action not in messages:raise ValueError('未知操作')
                return {'id':store.task_action(data['id'],action),'message':messages[action]},200
        return {'error':'页面不存在'},404
    except ValueError as exc:
        return {'error':str(exc)},400
    except (KeyError,TypeError,AttributeError):
        return {'error':'内容格式不正确，请检查问题、选项和参考答案'},400
    except Exception:
        return {'error':'操作未完成，请稍后重试'},500
