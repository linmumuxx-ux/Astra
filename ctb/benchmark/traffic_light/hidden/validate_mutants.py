import os
from mutants import MUTANTS
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src=open(os.path.join(ROOT,'implementation','controller.py'),encoding='utf-8').read()
missing=[bug_id for bug_id,(old,_) in MUTANTS.items() if old not in src]
if missing: raise SystemExit('missing mutation anchors: %s' % missing)
print('OK: %d mutation anchors valid' % len(MUTANTS))
