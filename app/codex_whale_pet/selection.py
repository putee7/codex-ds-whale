"""Keep animated local assets out of cloud migration, only while Codex is closed."""
import copy
import json
import re
import time
import tomllib
import uuid

from .files import OWNER, PET_ID, atomic_bytes, atomic_json, control_dir, read_json

MIGRATED='migrated-cloud-pet-ids-v1'
PENDING='pending-cloud-pet-migrations-v1'
OBSERVED='last-observed-cloud-pet-selection-v1'


def local_config(original,expected):
    text=original.decode('utf-8-sig')
    selected=tomllib.loads(text).get('desktop',{}).get('selected-avatar-id')
    if selected==PET_ID or selected!=expected:
        return original  # A later manual choice takes precedence over a queued repair.
    newline='\r\n' if '\r\n' in text else '\n'
    pattern=r'(^\[desktop\][ \t]*(?:#[^\r\n]*)?\r?\n)(.*?)(?=^\[|\Z)'
    def replace(section):
        body,count=re.subn(r'^(\s*selected-avatar-id\s*=\s*)(["\']).*?\2',
            lambda match:match[1]+json.dumps(PET_ID),section[2],count=1,flags=re.M)
        if count==0 and selected is None:
            body='selected-avatar-id = '+json.dumps(PET_ID)+newline+body
        elif count!=1:
            raise ValueError('Unsupported Pet selection TOML; configuration was not changed.')
        return section[1]+body
    updated,count=re.subn(pattern,replace,text,count=1,flags=re.M|re.S)
    if count==0 and selected is None and 'desktop' not in tomllib.loads(text):
        updated=text+('' if not text or text.endswith('\n') else newline)+newline+'[desktop]'+newline+'selected-avatar-id = '+json.dumps(PET_ID)+newline
    if tomllib.loads(updated).get('desktop',{}).get('selected-avatar-id')!=PET_ID:
        raise ValueError('Unsupported desktop TOML; configuration was not changed.')
    return (b'\xef\xbb\xbf' if original.startswith(b'\xef\xbb\xbf') else b'')+updated.encode('utf-8')


def local_state(original):
    value=json.loads(original.decode('utf-8-sig'))
    updated=copy.deepcopy(value)
    atoms=updated.get('electron-persisted-atom-state')
    if not isinstance(atoms,dict) or not all(isinstance(atoms.get(key,{}),dict) for key in (MIGRATED,PENDING,OBSERVED)):
        raise ValueError('Unknown Codex Pet preference format; no preferences were changed.')
    migrated=atoms.get(MIGRATED,{})
    accounts=set(migrated)|set(atoms.get(OBSERVED,{}))
    if not accounts:
        raise ValueError('No cloud Pet account preference exists yet. Sign in to Codex, then close it once.')
    pending=atoms.setdefault(PENDING,{})
    aliases=[]
    for account in accounts:  # Migration records are account-specific; touch only this local Pet.
        mapping=migrated.get(account,{})
        failures=pending.setdefault(account,{})
        if not isinstance(mapping,dict) or not isinstance(failures,dict):
            raise ValueError('Unknown per-account Pet migration format; no preferences were changed.')
        alias=mapping.pop(PET_ID,None)
        if alias:
            if not isinstance(alias,str) or not alias.startswith('pet_'):
                raise ValueError('Unknown whale cloud migration target; no preferences were changed.')
            aliases.append(alias)
        failures[PET_ID]={'failedPermanently':True}
    payload=(json.dumps(updated,ensure_ascii=False,indent=2)+'\n').encode('utf-8') if updated!=value else original
    return payload,aliases


def request(home,selected):
    path=control_dir(home,True)/'local-mode.json'
    record=read_json(path) if path.exists() else {'owner':OWNER,'aliases':[]}
    if record.get('owner')!=OWNER:
        raise ValueError('Local Pet mode belongs to another owner.')
    record.update(enabled=True,activate_expected=selected,state='pending_codex_exit')
    atomic_json(path,record)
    return {'state':record['state'],'reason':'Close Codex once; runtime selection and migration preferences are cached until exit.'}


def maintain(home,is_closed):
    path=control_dir(home)/'local-mode.json'
    if not path.exists():
        return None
    record=read_json(path)
    if record.get('owner')!=OWNER:
        raise ValueError('Local Pet mode belongs to another owner.')
    if not record.get('enabled') or not is_closed():
        return None
    state=home/'.codex-global-state.json'
    config=home/'config.toml'
    originals={state:state.read_bytes(),config:config.read_bytes() if config.exists() else b''}
    payload,aliases=local_state(originals[state])
    atoms=json.loads(originals[state].decode('utf-8-sig'))['electron-persisted-atom-state']
    retained=record.setdefault('original_migrations',{})
    for account in set(atoms.get(MIGRATED,{}))|set(atoms.get(OBSERVED,{})):
        if account not in retained:
            retained[account]={key:atoms.get(key,{}).get(account,{}).get(PET_ID) for key in (MIGRATED,PENDING)}
    updates={state:payload,config:local_config(originals[config],record['activate_expected']) if 'activate_expected' in record else originals[config]}
    changes={file:data for file,data in updates.items() if data!=originals[file]}
    if changes:
        backup=path.parent/'preference-backups'/('local-mode-'+uuid.uuid4().hex)
        backup.mkdir(parents=True)
        for file in changes:
            atomic_bytes(backup/file.name,originals[file])
        atomic_json(path,record)  # Save undo data before a crash could leave only the preferences committed.
        written=[]
        try:
            for file,data in changes.items():  # Two preferences must commit together, with checked rollback.
                if not is_closed() or (file.read_bytes() if file.exists() else b'')!=originals[file]:
                    raise RuntimeError('Codex started or preferences changed during repair; repair cancelled.')
                atomic_bytes(file,data)
                written.append(file)
        except Exception:
            for file in reversed(written):
                if file.read_bytes()!=changes[file]:
                    raise RuntimeError('Preferences changed during rollback; restore the private preference backup manually.')
                atomic_bytes(file,originals[file])
            raise
    previous=dict(record)
    record.update(state='applied',aliases=sorted(set(record.get('aliases',[])+aliases)))
    record.pop('activate_expected',None)
    if changes or record!=previous:
        record['applied_at']=time.time()
        atomic_json(path,record)
    return {'state':'applied','changed_files':len(changes)}


def migrated(home,selected):
    if not isinstance(selected,str) or not selected.startswith('pet_'):
        return False
    atoms=read_json(home/'.codex-global-state.json').get('electron-persisted-atom-state',{})
    return any(mapping.get(PET_ID)==selected for mapping in atoms.get(MIGRATED,{}).values())


def restore_migration_preferences(home,is_closed):
    path=control_dir(home)/'local-mode.json'
    if not path.exists():
        return
    record=read_json(path)
    if not record.get('original_migrations'):
        return
    if not is_closed():
        raise RuntimeError('Close Codex before uninstalling so its local Pet migration preferences can be restored safely.')
    file=home/'.codex-global-state.json'
    original=file.read_bytes()
    value=json.loads(original.decode('utf-8-sig'))
    atoms=value['electron-persisted-atom-state']
    for account,entries in record['original_migrations'].items():
        for key,old in entries.items():
            current=atoms.setdefault(key,{}).setdefault(account,{})
            expected={'failedPermanently':True} if key==PENDING else None
            if current.get(PET_ID)==expected:
                if old is None:
                    current.pop(PET_ID,None)
                else:
                    current[PET_ID]=old
    if not is_closed() or file.read_bytes()!=original:
        raise RuntimeError('Codex started or preferences changed during uninstall; preferences were not overwritten.')
    atomic_json(file,value)
