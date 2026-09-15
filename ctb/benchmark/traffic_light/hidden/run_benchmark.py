import json, os, subprocess, sys

HERE=os.path.dirname(os.path.abspath(__file__))
ROOT=os.path.dirname(HERE)


def run(cmd, cwd):
    return subprocess.run(cmd,cwd=cwd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)


def main():
    correct=run([sys.executable,os.path.join(ROOT,'run_correct.py')],ROOT)
    print(correct.stdout,end='')
    if correct.returncode:
        raise SystemExit(correct.returncode)

    valid=run([sys.executable,os.path.join(HERE,'validate_mutants.py')],HERE)
    print(valid.stdout,end='')
    if valid.returncode:
        raise SystemExit(valid.returncode)

    evaluated=run([sys.executable,os.path.join(HERE,'evaluate.py')],HERE)
    print(evaluated.stdout,end='')
    if evaluated.returncode:
        raise SystemExit(evaluated.returncode)

    data=json.loads(evaluated.stdout)
    result_path=os.path.join(ROOT,'benchmark_result.json')
    summary_path=os.path.join(ROOT,'benchmark_summary.json')
    with open(result_path,'w',encoding='utf-8') as f:
        json.dump(data,f,ensure_ascii=False,indent=2)
    summary={
        'total_bugs':data['total'],
        'killed_bugs':data['killed_count'],
        'kill_rate':round(data['killed_count']/data['total']*100,2) if data['total'] else 0,
        'hit_bug_ids':data['hit_bug_ids'],
        'missed_bug_ids':data['missed_bug_ids'],
        'testcase_hits':data['testcase_hits'],
    }
    with open(summary_path,'w',encoding='utf-8') as f:
        json.dump(summary,f,ensure_ascii=False,indent=2)
    print('RESULT: %d/%d killed (%.2f%%)' % (summary['killed_bugs'],summary['total_bugs'],summary['kill_rate']))
    print('summary:',summary_path)


if __name__=='__main__':
    main()
