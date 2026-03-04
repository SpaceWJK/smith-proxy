import subprocess, os, sys

dir_ = r'D:\Vibe Dev\Slack Bot'
git = r'C:\Program Files\Git\cmd\git.exe'
log = r'D:\Vibe Dev\Slack Bot\git_setup.log'

def run(args):
    r = subprocess.run([git] + args, cwd=dir_, capture_output=True, text=True, timeout=10)
    return r.stdout.strip(), r.stderr.strip(), r.returncode

results = []

# .git 폴더가 없으면 init
if not os.path.exists(os.path.join(dir_, '.git')):
    out, err, code = run(['init'])
    results.append(f'init: {out or err} (rc={code})')
else:
    results.append('init: already initialized')

# user config
run(['config', 'user.email', 'qabot@example.com'])
run(['config', 'user.name', 'QA Bot'])

# add all
out, err, code = run(['add', '.'])
results.append(f'add: {out or err or "OK"} (rc={code})')

# status
out, err, code = run(['status', '--short'])
results.append(f'status:\n{out}')

# commit
out, err, code = run(['commit', '-m', 'feat: initial Slack notification bot'])
results.append(f'commit: {out or err} (rc={code})')

with open(log, 'w', encoding='utf-8') as f:
    f.write('\n'.join(results))
