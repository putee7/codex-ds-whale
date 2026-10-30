"""Build an offline Windows release from tracked source files plus verified CPython files."""
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
version='1.0.0'
runtime=json.loads((ROOT/'runtime-files.json').read_text(encoding='utf-8'))['files']
for relative,expected in runtime.items():
    file=ROOT/'runtime'/relative
    if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=expected:
        raise SystemExit(f'Official runtime file mismatch: {relative}')
tracked=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
tracked=[name for name in tracked if name]
if not tracked:
    raise SystemExit('Stage the clean source tree before building a release.')
for name in tracked:
    if name=='PROJECT_LOG.md' or name.startswith(('.git/','runtime/')) or '__pycache__' in name:
        raise SystemExit(f'Private/generated file is tracked: {name}')
out=ROOT/'dist'
out.mkdir(exist_ok=True)
archive=out/f'codex-whale-musume-v{version}-windows-x64.zip'
prefix=f'codex-whale-musume-v{version}'
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as package:
    for name in sorted(tracked):
        package.write(ROOT/name,prefix+'/'+name)
    for name in sorted(runtime):
        package.write(ROOT/'runtime'/name,prefix+'/runtime/'+name)
with zipfile.ZipFile(archive) as package:
    if package.testzip() is not None:
        raise SystemExit('Release ZIP integrity check failed.')
checksum=hashlib.sha256(archive.read_bytes()).hexdigest()
(out/'SHA256SUMS.txt').write_text(checksum+'  '+archive.name+'\n',encoding='ascii')
print(json.dumps({'archive':archive.name,'bytes':archive.stat().st_size,'sha256':checksum}))
