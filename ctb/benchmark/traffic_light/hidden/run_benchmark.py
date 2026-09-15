import subprocess, sys

steps = [
    [sys.executable, 'validate_mutants.py'],
    [sys.executable, '..' + '/run_correct.py'],
    [sys.executable, 'evaluate.py'],
]
for cmd in steps:
    code = subprocess.call(cmd)
    if code:
        raise SystemExit(code)
