"""Real Docker boundary tests. Opt-in locally; enabled in Linux CI."""
import base64
import os
import unittest
from executor.service import run_container


@unittest.skipUnless(os.environ.get('DOCKER_SMOKE') == '1', 'requires Docker image')
class DockerSmokeTests(unittest.TestCase):
    def test_files_packages_environment_network(self):
        code = '''import os, socket
import docx, pptx, openpyxl
assert docx.__paper_version__ and pptx.__paper_version__ and openpyxl.__paper_version__
assert 'PAPERINSTRUMENTS_API_KEY' not in os.environ
assert 'EXECUTOR_TOKEN' not in os.environ
assert open('input.txt').read() == 'example'
try:
    socket.create_connection(('1.1.1.1', 443), timeout=1)
except OSError:
    pass
else:
    raise AssertionError('network available')
w = openpyxl.Workbook()
w.active['A1'] = 2
w.save('result.xlsx')
assert openpyxl.load_workbook('result.xlsx').active['A1'].value == 2
print('verified')
'''
        result = run_container({'code': code, 'files': {'input.txt': base64.b64encode(b'example').decode()}})
        self.assertEqual(result['exit_code'], 0, result['output'])
        self.assertIn('result.xlsx', result['files'])
        self.assertIn('verified', result['output'])

    def test_timeout(self):
        result = run_container({'code': 'import time; time.sleep(100)', 'files': {}})
        self.assertEqual(result['exit_code'], 124)
