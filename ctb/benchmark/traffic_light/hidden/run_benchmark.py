import os, subprocess, sys
HERE=os.path.dirname(os.path.abspath(__file__))
steps=[
 [sys.executable,os.path.join(HERE,'validate_mutants.py')],
 [sys.executable,os.path.join(HERE,'..','run_correct.py')],
 [sys.executable,os.path.join(HERE,'evaluate.py')],
]
for cmd in steps:
    code=subprocess.call(cmd,cwd=HERE)
    if code: raise SystemExit(code)
