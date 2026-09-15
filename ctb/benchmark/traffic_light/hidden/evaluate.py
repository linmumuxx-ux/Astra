import json, os, re, subprocess, sys, tempfile
from mutants import MUTANTS
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def main():
    src=open(os.path.join(ROOT,'implementation','controller.py'),encoding='utf-8').read(); result={}
    for bug_id,(old,new) in MUTANTS.items():
        if old not in src:
            result[str(bug_id)]={'error':'mutation anchor missing'}; continue
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td,'implementation')); open(os.path.join(td,'implementation','__init__.py'),'w').close()
            open(os.path.join(td,'implementation','controller.py'),'w',encoding='utf-8').write(src.replace(old,new,1))
            for name in ('test_aw.py','test_submission.py'):
                open(os.path.join(td,name),'w',encoding='utf-8').write(open(os.path.join(ROOT,name),encoding='utf-8').read())
            proc=subprocess.run([sys.executable,'-m','unittest','-v','test_submission.py'],cwd=td,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            failed=[]
            failed.extend(re.findall(r'^(test_\w+).*\.\.\. (?:FAIL|ERROR)$',proc.stdout,re.M))
            failed.extend(re.findall(r'^(?:FAIL|ERROR): (test_\w+)',proc.stdout,re.M))
            result[str(bug_id)]={'killed':proc.returncode!=0,'testcases':sorted(set(failed))}
    inverse={}
    for bug_id,data in result.items():
        for tc in data.get('testcases',[]): inverse.setdefault(tc,[]).append(int(bug_id))
    payload={'bugs':result,'testcase_hits':inverse,'killed_count':sum(1 for x in result.values() if x.get('killed')),'total':len(MUTANTS)}
    print(json.dumps(payload,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
