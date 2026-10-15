"""Dedicated Linux executor host, behind HTTPS reverse proxy. Standard library only.

The only host subprocess is a fixed Docker command, never model-generated shell.
Use a dedicated rootless Docker daemon and a separate VM from the MCP/API secrets.
"""
import hmac
import json
import os
import re
import subprocess
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from agent import MAX_WIRE_BYTES, validate_files

SLOTS = threading.BoundedSemaphore(2)


def command(name):
    image = os.environ.get('EXECUTOR_IMAGE', '')
    if not re.fullmatch(r'(?:[A-Za-z0-9._:/-]+@)?sha256:[a-f0-9]{64}', image):
        raise ValueError('Set EXECUTOR_IMAGE to a locally built, digest-pinned image')
    return ['docker', 'run', '--rm', '--pull=never', '--name', name,
            '--network=none', '--read-only', '--cap-drop=ALL',
            '--security-opt=no-new-privileges', '--pids-limit=64',
            '--memory=512m', '--memory-swap=512m', '--cpus=1',
            '--ulimit', 'fsize=4194304:4194304', '--user=65534:65534',
            '--log-driver=none', '--tmpfs', '/work:rw,noexec,nosuid,size=32m,mode=1777',
            '--tmpfs', '/tmp:rw,noexec,nosuid,size=16m,mode=1777', '-i', image]


def run_container(payload):
    name = 'ultramarine-' + uuid.uuid4().hex
    proc = None
    try:
        proc = subprocess.Popen(command(name), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        result = bytearray()
        overflow = threading.Event()
        def read_output():
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                if len(result) + len(chunk) > MAX_WIRE_BYTES:
                    overflow.set()
                    proc.kill()
                    break
                result.extend(chunk)
        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        # A writer thread prevents a stopped container from blocking the deadline.
        def write_input():
            try:
                proc.stdin.write(json.dumps(payload).encode())
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
        threading.Thread(target=write_input, daemon=True).start()
        proc.wait(timeout=35)
        reader.join(timeout=2)
        if proc.returncode != 0 or reader.is_alive() or overflow.is_set():
            raise ValueError('container_failed')
        value = json.loads(result)
        validate_files(value['files'])
        if type(value.get('exit_code')) is not int or not isinstance(value.get('output'), str):
            raise ValueError('invalid_result')
        return value
    finally:
        if proc and proc.poll() is None:
            proc.kill()
            proc.wait(timeout=3)
        # Killing the Docker client alone does not necessarily kill its container.
        subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=5)


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *args):
        pass  # Never log authorization headers, code, files or raw errors.

    def respond(self, code, data):
        raw = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        token = os.environ.get('EXECUTOR_TOKEN', '')
        supplied = self.headers.get('Authorization', '')
        if len(token) < 32 or not hmac.compare_digest(supplied.encode(), ('Bearer ' + token).encode()):
            return self.respond(401, {'error': 'unauthorized'})
        if self.path != '/execute':
            return self.respond(404, {'error': 'not_found'})
        if not SLOTS.acquire(blocking=False):
            return self.respond(429, {'error': 'busy'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= MAX_WIRE_BYTES or self.headers.get('Transfer-Encoding'):
                raise ValueError('body_limit')
            data = json.loads(self.rfile.read(size))
            validate_files(data['files'])
            if not isinstance(data.get('code'), str) or len(data['code'].encode()) > 16000:
                raise ValueError('code_limit')
            result = run_container({'code': data['code'], 'files': data['files']})
            self.respond(200, result)
        except Exception:
            self.respond(400, {'error': 'execution_failed'})
        finally:
            SLOTS.release()


if __name__ == '__main__':
    if len(os.environ.get('EXECUTOR_TOKEN', '')) < 32:
        raise SystemExit('Configure EXECUTOR_TOKEN with at least 32 random characters')
    command('configuration-check')
    ThreadingHTTPServer(('127.0.0.1', 8090), Handler).serve_forever()
