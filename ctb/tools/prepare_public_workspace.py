import json, os, shutil, sys


def main():
    if len(sys.argv) != 3:
        raise SystemExit('usage: python prepare_public_workspace.py <question_dir> <workspace_dir>')

    question_dir=os.path.abspath(sys.argv[1])
    workspace_dir=os.path.abspath(sys.argv[2])
    manifest_path=os.path.join(question_dir,'public_files.json')
    manifest=json.load(open(manifest_path,encoding='utf-8'))

    os.makedirs(workspace_dir,exist_ok=True)
    copied=[]
    for rel in manifest['files']:
        src=os.path.abspath(os.path.join(question_dir,rel))
        if not src.startswith(question_dir + os.sep):
            raise SystemExit('invalid public path: %s' % rel)
        if not os.path.isfile(src):
            raise SystemExit('missing public file: %s' % rel)
        dst=os.path.join(workspace_dir,rel)
        os.makedirs(os.path.dirname(dst),exist_ok=True)
        shutil.copy2(src,dst)
        copied.append(rel)

    print('public workspace:',workspace_dir)
    for rel in copied:
        print('-',rel)


if __name__=='__main__':
    main()
