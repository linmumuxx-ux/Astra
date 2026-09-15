import json, os, re, shutil, subprocess, sys, tempfile
from mutants import MUTANTS

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TESTCASE = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(ROOT, 'test_submission.py')


def main():
    src = open(os.path.join(ROOT, 'implementation', 'controller.py'), encoding='utf-8').read()
    result = {}
    for bug_id, (old, new) in MUTANTS.items():
        if old not in src:
            result[str(bug_id)] = {'error': 'mutation anchor missing', 'killed': False, 'testcases': []}
            continue
        with tempfile.TemporaryDirectory() as td:
            os.makedirs(os.path.join(td, 'implementation'))
            open(os.path.join(td, 'implementation', '__init__.py'), 'w').close()
            open(os.path.join(td, 'implementation', 'controller.py'), 'w', encoding='utf-8').write(src.replace(old, new, 1))
            shutil.copy2(os.path.join(ROOT, 'test_aw.py'), os.path.join(td, 'test_aw.py'))
            shutil.copy2(TESTCASE, os.path.join(td, 'test_submission.py'))
            proc = subprocess.run([sys.executable, '-m', 'unittest', '-v', 'test_submission.py'], cwd=td, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10)
            failed = re.findall(r'^(test_\w+).*\.\.\. (?:FAIL|ERROR)$', proc.stdout, re.M)
            failed += re.findall(r'^(?:FAIL|ERROR): (test_\w+)', proc.stdout, re.M)
            result[str(bug_id)] = {'killed': proc.returncode != 0, 'testcases': sorted(set(failed))}
    inverse = {}
    for bug_id, data in result.items():
        for tc in data.get('testcases', []):
            inverse.setdefault(tc, []).append(int(bug_id))
    payload = {
        'bugs': result,
        'testcase_hits': {k: sorted(v) for k, v in sorted(inverse.items())},
        'killed_count': sum(1 for x in result.values() if x.get('killed')),
        'total': len(MUTANTS),
        'missed_bug_ids': sorted(int(k) for k, v in result.items() if not v.get('killed')),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
