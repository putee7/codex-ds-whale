"""Fail publication without echoing sensitive matches. Runtime is verified by its official hashes."""
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SKIP={'.git','runtime','build','dist','__pycache__','.venv'}
FORBIDDEN={'auth.json','config.toml','.codex-global-state.json','install-state.json','motion-status.json','PROJECT_LOG.md'}
patterns={
    'credential':re.compile(r'(?:gh[pousr]_[A-Za-z0-9_]{25,}|sk-[A-Za-z0-9_-]{25,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)'),
    'private_chat_id':re.compile(r'(?:wxid_[A-Za-z0-9_]+|pet_[0-9a-f]{24,})')}
home=str(Path.home()).replace('\\','/').casefold()
failures=[]
checked=0
for path in ROOT.rglob('*'):  # Publication must inspect every exported file, rather than sample a few names.
    relative=path.relative_to(ROOT)
    if any(part in SKIP for part in relative.parts) or not path.is_file() or path.name=='PROJECT_LOG.md':
        continue
    checked+=1
    if path.name in FORBIDDEN or path.suffix in ('.asar','.log'):
        failures.append((relative.as_posix(),'private/runtime file'))
    if path.suffix.lower() in ('.py','.ps1','.cmd','.json','.md','.txt','.yml','.toml') or path.name in ('LICENSE','.gitignore','.gitattributes'):
        text=path.read_text(encoding='utf-8-sig')
        normalized=text.replace('\\\\','\\').replace('\\','/').casefold()
        if home in normalized:
            failures.append((relative.as_posix(),'absolute publisher home path'))
        for label,pattern in patterns.items():
            if pattern.search(text):failures.append((relative.as_posix(),label))
if failures:
    for file,label in failures:print(f'BLOCKED: {file}: {label}')
    raise SystemExit(1)
print(f'Public source check passed: {checked} files; no private match values were printed.')
