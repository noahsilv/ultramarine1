"""Runs INSIDE the disposable container, never on the MCP/executor host."""
import base64
import json
import os
import pathlib
import re
import subprocess
import sys

payload = json.loads(sys.stdin.buffer.read(4 * 1024 * 1024))
work = pathlib.Path('/work')
for name, value in payload['files'].items():
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', name):
        raise ValueError('filename')
    (work / name).write_bytes(base64.b64decode(value, validate=True))
code_path = pathlib.Path('/tmp/task.py')
code_path.write_text(payload['code'], encoding='utf-8')
with open('/tmp/output', 'wb') as output:
    try:
        run = subprocess.run([sys.executable, '-I', str(code_path)], cwd=work,
            env={'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': '/tmp', 'TMPDIR': '/tmp'},
            stdout=output, stderr=subprocess.STDOUT, timeout=25)
        exit_code = run.returncode
    except subprocess.TimeoutExpired:
        exit_code = 124
files = {}
total = 0
for path in sorted(work.iterdir()):
    if path.is_symlink() or not path.is_file() or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', path.name):
        continue
    size = path.stat().st_size
    if size + total > 2 * 1024 * 1024 or len(files) >= 20:
        raise ValueError('artifact_limit')
    total += size
    files[path.name] = base64.b64encode(path.read_bytes()).decode()
with open('/tmp/output', 'rb') as output:
    text = output.read(16000).decode('utf-8', errors='replace')
print(json.dumps({'exit_code': exit_code, 'output': text, 'files': files}))
