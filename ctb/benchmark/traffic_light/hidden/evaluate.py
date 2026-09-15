import json, os, re, subprocess, sys, tempfile
from mutants import MUTANTS

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIMEOUT_SEC=15


def main():
    src=open(os.path.join(ROOT,'implementation','controller.py'),encoding='utf-8').read(); result={}
    for bug_id,(old,new) in MUTANTS.items():
        if old not in src:
            result[str(bug_id)]={'killed':False,'testcases':[],'error':'mutation anchor missing'}; continue
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td,'implementation')); open(os.path.join(td,'implementation','__init__.py'),'w').close()
            open(os.path.join(td,'implementation','controller.py'),'w',encoding='utf-8').write(src.replace(old,new,1))
            for name in ('test_aw.py','test_submission.py'):
                open(os.path.join(td,name),'w',encoding='utf-8').write(open(os.path.join(ROOT,name),encoding='utf-8').read())
            try:
                proc=subprocess.run([sys.executable,'-m','unittest','-v','test_submission.py'],cwd=td,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=TIMEOUT_SEC)
            except subprocess.TimeoutExpired:
                result[str(bug_id)]={'killed':False,'testcases':[],'error':'evaluation timeout'}; continue
            failed=re.findall(r'^(test_\w+).*\.\.\. (?:FAIL|ERROR)$',proc.stdout,re.M)
            failed+=re.findall(r'^(?:FAIL|ERROR): (test_\w+)',proc.stdout,re.M)
            result[str(bug_id)]={'killed':proc.returncode!=0,'testcases':sorted(set(failed))}
    inverse={}
    for bug_id,data in result.items():
        for tc in data.get('testcases',[]): inverse.setdefault(tc,[]).append(int(bug_id))
    killed=[int(k) for k,v in result.items() if v.get('killed')]
    errors={k:v['error'] for k,v in result.items() if v.get('error')}
    output={
        'bugs':result,
        'testcase_hits':{k:sorted(v) for k,v in sorted(inverse.items())},
        'killed_count':len(killed),
        'total':len(MUTANTS),
        'hit_bug_ids':sorted(killed),
        'missed_bug_ids':sorted(set(MUTANTS)-set(killed)),
        'errors':errors,
    }
    print(json.dumps(output,ensure_ascii=False,indent=2))
    if errors: raise SystemExit(2)

if __name__=='__main__': main()
