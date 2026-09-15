import json,os,re,subprocess,sys,tempfile
from mutants import MUTANTS
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def main():
 src=open(os.path.join(ROOT,'implementation','controller.py'),encoding='utf-8').read(); result={}
 for bug_id,(old,new) in MUTANTS.items():
  if old not in src: result[str(bug_id)]={'error':'mutation anchor missing'}; continue
  with tempfile.TemporaryDirectory() as td:
   os.makedirs(os.path.join(td,'implementation')); open(os.path.join(td,'implementation','__init__.py'),'w').close()
   open(os.path.join(td,'implementation','controller.py'),'w',encoding='utf-8').write(src.replace(old,new,1))
   for n in ('test_aw.py','test_submission.py'): open(os.path.join(td,n),'w',encoding='utf-8').write(open(os.path.join(ROOT,n),encoding='utf-8').read())
   p=subprocess.run([sys.executable,'-m','unittest','-v','test_submission.py'],cwd=td,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
   failed=re.findall(r'^(?:FAIL|ERROR): (test_\w+)',p.stdout,re.M)
   result[str(bug_id)]={'killed':p.returncode!=0,'testcases':sorted(set(failed))}
 print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
