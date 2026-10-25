"""Local integration check: history HTTP endpoint and clean termination."""
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

process = subprocess.Popen([sys.executable, 'eval.py', 'serve', '--port', '18787'], stdout=subprocess.PIPE)
try:
    for attempt in range(50):
        try:
            local = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with local.open('http://127.0.0.1:18787', timeout=1) as response:
                runs = json.load(response)
            assert runs and all('summary' in run for run in runs)
            print('History HTTP integration passed')
            break
        except OSError:
            time.sleep(.1)
    else:
        raise RuntimeError('History service did not start')
finally:
    process.terminate()
    process.wait(timeout=5)
