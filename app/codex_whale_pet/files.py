"""Narrow file operations shared by installation and the asset controller."""
import hashlib
import json
import os
import tempfile
from pathlib import Path, PurePosixPath

PET_ID = 'custom:whale-musume'
BASE = 'spritesheet-look-breath.png'
OWNER = 'putee7/codex-whale-musume'


def control_dir(home,create=False):
    path=Path(home)/'pet-tools/codex-whale-control'
    marker=path/'owner.json'
    if path.exists() and (not marker.exists() or read_json(marker).get('owner')!=OWNER):
        raise ValueError('Controller state directory has no matching ownership marker.')
    if create and not path.exists():
        path.mkdir(parents=True)
        atomic_json(marker,{'owner':OWNER})
    return path


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def atomic_bytes(path, payload):
    path = Path(path)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.whale-', suffix='.tmp', delete=False) as stream:
        stream.write(payload)
        temporary = Path(stream.name)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path, value):
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode('utf-8'))


def contained(root, relative, exists=False):
    """Reject traversal, alternate Windows separators/streams, and symlink escapes."""
    root = Path(root).resolve()
    name = PurePosixPath(relative)
    if not relative or name.is_absolute() or '..' in name.parts or '\\' in relative or ':' in relative:
        raise ValueError(f'Unsafe package path: {relative!r}')
    target = (root / relative).resolve(strict=exists)
    if not target.is_relative_to(root) or target == root:
        raise ValueError(f'Package path leaves its directory: {relative!r}')
    return target


def verify_assets(pet, manifest, live=False):
    entries = manifest['files']
    if manifest.get('pet_id') != 'whale-musume' or len(entries) < 24:
        raise ValueError('Incomplete pet asset manifest.')
    for name, expected in entries.items():  # Every shipped file must be verified before it becomes live.
        path = contained(pet, name, exists=True)
        if live and name=='pet.json':
            continue
        if not path.is_file() or path.stat().st_size != expected['bytes'] or digest(path) != expected['sha256']:
            raise ValueError(f'Asset checksum mismatch: {name}')
    metadata = read_json(contained(pet, 'motion-assets.json', exists=True))
    if metadata['source_sha256'] != entries['spritesheet.webp']['sha256']:
        raise ValueError('Artwork and motion assets refer to different masters.')
    actions = metadata['hover_actions']
    if set(actions) != {'hop', 'waving', 'eating'} or metadata['hover_source_sha256'] != metadata['source_sha256']:
        raise ValueError('Invalid hover action registry.')
    for action in actions.values():
        path = contained(pet, action['path'], exists=True)
        if digest(path) != action['sha256']:
            raise ValueError('Hover action does not match its checksum.')
    contained(pet, metadata['hover_live_path'])
    if live:
        current=read_json(Path(pet)/'pet.json')
        expected=manifest['pet_manifest']
        allowed={BASE,metadata['hover_live_path'],*(f"{metadata['bank']}/{index:02}.webp" for index in range(16))}
        if {key:value for key,value in current.items() if key!='spritesheetPath'}!={key:value for key,value in expected.items() if key!='spritesheetPath'} or current['spritesheetPath'] not in allowed:
            raise ValueError('Live Pet manifest has an unexpected identity or image path.')
    return metadata
