import io, json, os, sys, unittest
from mutants import MUTANTS

ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,ROOT)

import test_aw
import test_submission


def make_controller(source, bug_id):
    ns={'__name__':'ctb_mutant_%s' % bug_id}
    exec(compile(source,'<mutant-%s>' % bug_id,'exec'),ns)
    return ns['TrafficController']


def main():
    src=open(os.path.join(ROOT,'implementation','controller.py'),encoding='utf-8').read(); result={}
    for bug_id,(old,new) in MUTANTS.items():
        if old not in src:
            result[str(bug_id)]={'killed':False,'testcases':[],'error':'mutation anchor missing'}; continue
        try:
            test_aw.TrafficController=make_controller(src.replace(old,new,1),bug_id)
            suite=unittest.defaultTestLoader.loadTestsFromTestCase(test_submission.TestTrafficController)
            run=unittest.TextTestRunner(stream=io.StringIO(),verbosity=0).run(suite)
            failed=sorted({case.id().rsplit('.',1)[-1] for case,_ in run.failures+run.errors})
            result[str(bug_id)]={'killed':bool(failed),'testcases':failed}
        except Exception as exc:
            result[str(bug_id)]={'killed':False,'testcases':[],'error':'evaluator error: %s' % exc}
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
