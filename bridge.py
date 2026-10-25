"""One application request through stdin/stdout; never executes shell input."""
import json
import sys
import application

if __name__=='__main__':
    try:
        request=json.loads(sys.stdin.read(4*1024*1024+1))
        value,status=application.dispatch(request['method'],request['path'],request.get('data'))
    except Exception:
        value,status={'error':'本机服务请求格式不正确'},400
    sys.stdout.write(json.dumps({'value':value,'status':status},ensure_ascii=False,allow_nan=False))
