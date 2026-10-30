"""Transactional installation and explicit maintenance; no account/configuration writes."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from . import __version__
from .files import BASE, OWNER, atomic_bytes, atomic_json, contained, control_dir, read_json, verify_assets


def default_home():
    return Path(os.environ.get('CODEX_HOME', Path.home()/'.codex')).expanduser().resolve()


def default_install():
    local=os.environ.get('LOCALAPPDATA')
    if not local:
        raise ValueError('LOCALAPPDATA is unavailable; provide --install-dir explicitly.')
    return (Path(local)/'CodexWhaleMusume').resolve()


def state_file(root):
    return root/'install-state.json'


def state(root):
    value=read_json(state_file(root))
    if value.get('owner')!=OWNER or Path(value['install_root']).resolve()!=root.resolve():
        raise ValueError('Install ownership marker does not match this directory.')
    return value


def remove_child(parent,name):
    target=contained(parent,name,True)
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()


def stop(home,timeout=10,expect_running=True):
    pet=home/'pets/whale-musume'
    if not pet.is_dir():
        return
    atomic_bytes(pet/'motion-stop',b'')
    control=control_dir(home)
    known=(control/'started.json').is_file() or (pet/'motion-status.json').is_file()
    if expect_running or known:
        control=control_dir(home,create=True)
        atomic_bytes(control/'motion-stop',b'')
    else:
        return  # A no-start installation with no registered process cannot own the global mutex.
    if os.name!='nt':
        return
    from .windows import controller_running
    deadline=time.monotonic()+timeout
    while controller_running() and time.monotonic()<deadline:  # Wait only for our named controller; never kill a process.
        time.sleep(.1)
    if controller_running():
        raise TimeoutError('Controller did not stop; no files were replaced.')


def install(package,home,root,use_current_python=False):
    package,home,root=package.resolve(),home.resolve(),root.resolve()
    if root==home or home.is_relative_to(root) or root.is_relative_to(home/'pets') or root==Path(root.anchor):
        raise ValueError('Unsafe installation directory; use a dedicated application folder.')
    if package.is_relative_to(root) or root.is_relative_to(package):
        raise ValueError('Installation directory must be outside the extracted source/release folder.')
    previous_state=state(root) if state_file(root).exists() else None
    if previous_state and Path(previous_state['codex_home']).resolve()!=home:
        raise ValueError('This install directory belongs to another CODEX_HOME; uninstall it first or use a separate --install-dir.')
    if root.exists() and any(root.iterdir()) and previous_state is None:
        raise ValueError('Refusing to overwrite a nonempty directory without this project ownership marker.')
    manifest=read_json(package/'assets-manifest.json')
    verify_assets(package/'pet',manifest)
    runtime=package/'runtime'
    bundled=(runtime/'python.exe').is_file()
    if not bundled and not use_current_python:
        raise ValueError('Bundled runtime is missing. Run Install.cmd, or explicitly use --use-current-python for source development.')
    home.mkdir(parents=True,exist_ok=True)
    root.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.whale-stage-',dir=home))
    tools=Path(tempfile.mkdtemp(prefix='.whale-tools-',dir=root.parent))
    pet=home/'pets/whale-musume'
    backup=None
    activated=False
    swapped=[]
    old_records={name:(root/name).read_bytes() if (root/name).exists() else None for name in ('assets-manifest.json','install-state.json')}
    try:
        shutil.copytree(package/'pet',stage/'pet')
        verify_assets(stage/'pet',manifest)
        install_id=uuid.uuid4().hex
        atomic_json(stage/'pet/.codex-whale-owner.json',{'owner':OWNER,'install_id':install_id})
        shutil.copytree(package/'app',tools/'app',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        if bundled:
            shutil.copytree(runtime,tools/'runtime')
        python=root/'runtime/python.exe' if bundled else Path(sys.executable).resolve()
        pythonw=python.with_name('pythonw.exe')
        if os.name=='nt' and not ((tools/'runtime/pythonw.exe').is_file() if bundled else pythonw.is_file()):
            raise ValueError('The selected runtime has no pythonw.exe.')
        stop(home,expect_running=bool(previous_state.get('controller_started')) if previous_state else (pet/'motion-assets.json').is_file())
        if pet.exists():
            backup=home/'pet-repair-backups'/('whale-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+uuid.uuid4().hex[:8])
            backup.mkdir(parents=True)
            if not pet.resolve().is_relative_to((home/'pets').resolve()) or not backup.resolve().is_relative_to((home/'pet-repair-backups').resolve()):
                raise ValueError('Pet backup paths leave the named directories.')
            os.replace(pet,backup/'previous-pet')
        pet.parent.mkdir(exist_ok=True)
        os.replace(stage/'pet',pet)
        activated=True
        root.mkdir(exist_ok=True)
        for name in ('app','runtime'):
            if (tools/name).exists():
                if (root/name).exists():
                    os.replace(root/name,tools/('previous-'+name))
                os.replace(tools/name,root/name)
                swapped.append(name)
        old_marker=read_json(backup/'previous-pet/.codex-whale-owner.json') if backup and (backup/'previous-pet/.codex-whale-owner.json').exists() else {}
        upgrade=previous_state and old_marker.get('owner')==OWNER and old_marker.get('install_id')==previous_state['install_id']
        original_backup=previous_state.get('original_backup') if upgrade else str(backup/'previous-pet') if backup else None
        record={'schema':1,'owner':OWNER,'version':__version__,'install_id':install_id,'install_root':str(root),
                'codex_home':str(home),'python':str(python),'pythonw':str(pythonw),
                'controller_started':False,
                'original_backup':original_backup,'latest_backup':str(backup) if backup else None}
        atomic_json(root/'assets-manifest.json',manifest)
        atomic_json(state_file(root),record)
        return record
    except Exception:
        for name in ('app','runtime'):
            if name in swapped and (root/name).exists():
                remove_child(root,name)
            if (tools/('previous-'+name)).exists():
                os.replace(tools/('previous-'+name),root/name)
        for name,payload in old_records.items():
            if payload is not None:
                atomic_bytes(root/name,payload)
            elif (root/name).exists():
                (root/name).unlink()
        if activated and pet.exists():
            marker=read_json(pet/'.codex-whale-owner.json')
            if marker.get('install_id')==install_id:
                remove_child(home/'pets','whale-musume')
        if backup and (backup/'previous-pet').exists() and not pet.exists():
            os.replace(backup/'previous-pet',pet)
        raise
    finally:
        # Both temporary directories were created by this invocation below the checked target parents.
        if stage.exists():
            remove_child(home,stage.name)
        if tools.exists():
            remove_child(root.parent,tools.name)


def start(root,allow_untested=False):
    record=state(root)
    home=Path(record['codex_home'])
    verify_assets(home/'pets/whale-musume',read_json(root/'assets-manifest.json'),live=True)
    if os.name!='nt':
        raise OSError('Enhanced native Pet control is supported on Windows only.')
    from .windows import check_version,controller_running
    version=check_version(allow_untested)
    if controller_running():
        return {'state':'already_running','codex_version':version}
    log=root/'controller-error.log'
    command=[record['pythonw'],str(root/'app/run.py'),'run','--home',str(home)]
    if allow_untested:
        command.append('--allow-untested')
    with log.open('ab') as errors:
        control=control_dir(home,create=True)
        (control/'motion-stop').unlink(missing_ok=True)
        (home/'pets/whale-musume/motion-stop').unlink(missing_ok=True)
        record['controller_started']=True
        atomic_json(state_file(root),record)
        process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=errors,
            creationflags=subprocess.CREATE_NO_WINDOW|subprocess.DETACHED_PROCESS)
    time.sleep(1)
    if process.poll() is not None and process.returncode!=0:
        raise RuntimeError(f'Controller failed; see {log.name}.')
    path=home/'pets/whale-musume/motion-status.json'
    result=read_json(path) if path.exists() else {'state':'starting'}
    if result.get('state')=='error':
        raise RuntimeError(result.get('reason','Controller failed.'))
    if process.poll() is not None and not controller_running():
        raise RuntimeError(f'Controller exited unexpectedly; see {log.name}.')
    return {**result,'codex_version':version,'allow_untested':allow_untested}


def doctor(root):
    record=state(root)
    home=Path(record['codex_home'])
    metadata=verify_assets(home/'pets/whale-musume',read_json(root/'assets-manifest.json'),live=True)
    result={'installed_version':record['version'],'asset_checksums':'ok','runtime_exists':Path(record['python']).is_file(),
            'pet_id':'whale-musume','motion_master':metadata['source_sha256']}
    path=home/'pets/whale-musume/motion-status.json'
    result['controller']=read_json(path) if path.exists() else {'state':'not_started'}
    if os.name=='nt':
        from .windows import APP_VERSION,installed_version,selected_pet
        version=installed_version()
        result.update(codex_version=version,tested_codex_version=APP_VERSION,version_tested=version==APP_VERSION,
                      whale_selected=selected_pet(home)=='custom:whale-musume')
    return result


def uninstall(root):
    record=state(root)
    home=Path(record['codex_home']).resolve()
    pet=home/'pets/whale-musume'
    marker=read_json(pet/'.codex-whale-owner.json')
    if marker.get('owner')!=OWNER or marker.get('install_id')!=record['install_id']:
        raise ValueError('Installed Pet ownership changed; nothing was removed.')
    if Path(sys.executable).resolve().is_relative_to(root/'runtime'):
        raise ValueError('Run Uninstall.cmd from the extracted release, not the installed runtime that must be removed.')
    original=Path(record['original_backup']).resolve() if record.get('original_backup') else None
    if original and (not original.is_relative_to((home/'pet-repair-backups').resolve()) or not original.is_dir()):
        raise ValueError('Original Pet backup is missing or outside its backup directory; nothing was removed.')
    stop(home,expect_running=bool(record.get('controller_started')))
    pet_backup=home/'pet-repair-backups'/('uninstall-'+uuid.uuid4().hex)
    pet_backup.mkdir(parents=True)
    tools=Path(tempfile.mkdtemp(prefix='.whale-uninstall-',dir=root.parent))
    moved=[]
    restored=False
    try:
        os.replace(pet,pet_backup/'removed-pet')
        if original:
            os.replace(original,pet)
            restored=True
        for name in ('app','runtime','assets-manifest.json','controller-error.log','install-state.json'):
            if (root/name).exists():
                os.replace(root/name,tools/name)
                moved.append(name)
    except Exception:
        for name in reversed(moved):
            os.replace(tools/name,root/name)
        if restored:
            os.replace(pet,original)
        if (pet_backup/'removed-pet').exists():
            os.replace(pet_backup/'removed-pet',pet)
        raise
    else:
        remove_child(home/'pet-repair-backups',pet_backup.name)
        remove_child(root.parent,tools.name)
        control=control_dir(home)
        if control.exists():
            remove_child(home/'pet-tools',control.name)
    remaining=any(root.iterdir())
    if not remaining:
        root.rmdir()
    return {'uninstalled':True,'previous_pet_restored':bool(original),'additional_files_retained':remaining}
