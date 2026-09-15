import json
import shutil
import sys
from pathlib import Path


FORBIDDEN_PARTS = {
    'hidden',
    'implementation',
    'candidate',
    'results',
    'history',
}


def fail(message):
    raise SystemExit(message)


def main():
    if len(sys.argv) != 3:
        fail('usage: python prepare_public_workspace.py <question_dir> <workspace_dir>')

    question_dir = Path(sys.argv[1]).resolve()
    workspace_dir = Path(sys.argv[2]).resolve()

    if not question_dir.is_dir():
        fail('question_dir not found: %s' % question_dir)
    if workspace_dir == question_dir or question_dir in workspace_dir.parents:
        fail('workspace_dir must be outside question_dir')

    manifest_path = question_dir / 'public_files.json'
    if not manifest_path.is_file():
        fail('missing public_files.json: %s' % manifest_path)

    with manifest_path.open(encoding='utf-8') as f:
        manifest = json.load(f)

    files = manifest.get('files')
    if not isinstance(files, list) or not files:
        fail('public_files.json must contain a non-empty files list')

    # Always rebuild from an empty directory. Reusing an existing workspace can
    # otherwise leak hidden/candidate files left by a previous run.
    if workspace_dir.exists():
        shutil.rmtree(str(workspace_dir))
    workspace_dir.mkdir(parents=True)

    copied = []
    for rel in files:
        if not isinstance(rel, str) or not rel:
            fail('invalid public path: %r' % rel)

        rel_path = Path(rel)
        if rel_path.is_absolute() or '..' in rel_path.parts:
            fail('invalid public path: %s' % rel)
        if any(part.lower() in FORBIDDEN_PARTS for part in rel_path.parts):
            fail('forbidden public path: %s' % rel)

        src = (question_dir / rel_path).resolve()
        if question_dir not in src.parents:
            fail('public path escapes question_dir: %s' % rel)
        if not src.is_file():
            fail('missing public file: %s' % rel)

        dst = workspace_dir / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))
        copied.append(rel)

    print('public workspace:', workspace_dir)
    for rel in copied:
        print('-', rel)


if __name__ == '__main__':
    main()
