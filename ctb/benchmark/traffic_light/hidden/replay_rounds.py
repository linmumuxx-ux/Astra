import json, os, subprocess, sys

HERE=os.path.dirname(os.path.abspath(__file__))
ROOT=os.path.dirname(HERE)
EVALUATOR=os.path.join(HERE,'evaluate.py')

ROUNDS=[
    ('round-1',os.path.join(ROOT,'history','v1_test_submission.py')),
    ('round-2',os.path.join(ROOT,'test_submission.py')),
]

for name,path in ROUNDS:
    proc=subprocess.run([sys.executable,EVALUATOR,path],cwd=HERE,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    if proc.returncode:
        print(proc.stdout)
        raise SystemExit(proc.returncode)
    data=json.loads(proc.stdout)
    print('%s: %d/%d killed, missed=%s' % (name,data['killed_count'],data['total'],data['missed_bug_ids']))
