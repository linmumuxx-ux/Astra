import os, subprocess, sys
HERE=os.path.dirname(os.path.abspath(__file__))
for script in ('validate_mutants.py','evaluate.py'):
    code=subprocess.call([sys.executable,os.path.join(HERE,script)],cwd=HERE)
    if code: raise SystemExit(code)
