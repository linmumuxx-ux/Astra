import os, subprocess, sys
ROOT=os.path.dirname(os.path.abspath(__file__))
raise SystemExit(subprocess.call([sys.executable,'-m','unittest','-v','test_submission.py'],cwd=ROOT))
