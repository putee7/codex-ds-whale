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

COMMANDS={'Start.cmd':'start','Stop.cmd':'stop','Doctor.cmd':'doctor','Repair.cmd':'repair',
    'EnableRecovery.cmd':'enable-recovery','DisableRecovery.cmd':'disable-recovery'}


def default_home():
    return Path(os.environ.get('CODEX_HOME', Path.home()/'.codex')).expanduser().resolve()


def default_install(home=None):
    home=home or default_home()
    pointer=control_dir(home)/'installation.json'
    if pointer.exists():
        binding=read_json(pointer)
        if binding.get('owner')!=OWNER:
            raise ValueError('Installation binding belongs to another owner.')
        return Path(binding['install_root']).resolve()
    return (home/'pet-tools/codex-whale-runtime').resolve()


def bind(root,home):
    atomic_json(control_dir(home,True)/'installation.json',{'owner':OWNER,'install_root':str(root.resolve())})


def migrate_legacy(root,home):
    """Move the owned legacy installation once; never leave another runtime copy."""
    local=os.environ.get('LOCALAPPDATA')
    candidates=[Path(local)] if local else []
    candidates.append(Path.home()/'AppData/Local/Packages/OpenAI.Codex_2p2nqsd0c76g0/LocalCache/Local')
    files=[folder/'CodexWhaleMusume/install-state.json' for folder in candidates if (folder/'CodexWhaleMusume/install-state.json').exists()]
    if not files or root.exists():
        return
    records={value['install_root']:value for value in map(read_json,files)}
    if len(records)!=1:
        raise ValueError('Multiple legacy runtime directories exist; resolve their ownership before upgrading.')
    old=next(iter(records.values()))
    if old.get('owner')!=OWNER or Path(old['codex_home']).resolve()!=home:
        raise ValueError('Legacy installation ownership/home mismatch; no files were moved.')
    if tuple(map(int,old['version'].split('.')))>tuple(map(int,__version__.split('.'))):
        raise ValueError('Refusing to migrate/downgrade a newer installation with an older release.')
    old_root=Path(old['install_root']).resolve()
    state(old_root)
    if root!=(home/'pet-tools/codex-whale-runtime').resolve() or root.is_relative_to(old_root) or old_root.is_relative_to(root):
        raise ValueError('Legacy migration target must be the canonical Pet tools directory.')
    from . import recovery
    had_task=recovery.task(old_root,'query').get('registered',False)
    stop(home)
    if had_task:
        recovery.task(old_root,'remove')
    root.parent.mkdir(parents=True,exist_ok=True)
    moved=False
    try:
        os.replace(old_root,root)
        moved=True
        record={**old,'install_root':str(root),'python':str(root/'runtime/python.exe'),'pythonw':str(root/'runtime/pythonw.exe')}
        atomic_json(state_file(root),record)
        bind(root,home)
    except Exception:
        if moved:
            atomic_json(state_file(root),old)
            os.replace(root,old_root)
        if had_task:
            recovery.task(old_root,'enable')
        raise


def runtime_identity(root):
    import hashlib
    source=sorted((root/'app').rglob('*.py'))
    if not source:
        raise ValueError('Installed application source is missing.')
    return {'version':read_json(state_file(root))['version'],'install_root':str(root.resolve()),
        'code_sha256':hashlib.sha256(b''.join(file.relative_to(root).as_posix().encode()+file.read_bytes() for file in source)).hexdigest()}


def check_running(root,home):
    started=read_json(control_dir(home)/'started.json')
    identity=runtime_identity(root)
    from .windows import app_path
    if any(started.get(key)!=value for key,value in identity.items()) or Path(app_path(started['pid'])).resolve()!=Path(state(root)['pythonw']).resolve():
        raise RuntimeError('A controller from another path or build is running. Stop it before starting this installation.')
    return {**identity,'pid':started['pid']}


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
    from .windows import controller_running,wait_for_exit
    started=read_json(control/'started.json') if (control/'started.json').exists() else None
    deadline=time.monotonic()+timeout
    while controller_running() and time.monotonic()<deadline:  # Wait only for our named controller; never kill a process.
        time.sleep(.1)
    if controller_running():
        raise TimeoutError('Controller did not stop; no files were replaced.')
    if started and started.get('owner')==OWNER:
        executable=Path(started['install_root'])/'runtime/pythonw.exe' if started.get('install_root') else None
        wait_for_exit(started['pid'],max(0,deadline-time.monotonic()),executable)


def install(package,home,root,use_current_python=False):
    package,home,root=package.resolve(),home.resolve(),root.resolve()
    if root==home or home.is_relative_to(root) or root.is_relative_to(home/'pets') or root==Path(root.anchor):
        raise ValueError('Unsafe installation directory; use a dedicated application folder.')
    if package.is_relative_to(root) or root.is_relative_to(package):
        raise ValueError('Installation directory must be outside the extracted source/release folder.')
    previous_state=state(root) if state_file(root).exists() else None
    bound=control_dir(home)/'installation.json'
    if bound.exists() and default_install(home)!=root:
        raise ValueError('This Codex home already has a canonical installation; upgrade that directory instead.')
    if previous_state and tuple(map(int,previous_state['version'].split('.')))>tuple(map(int,__version__.split('.'))):
        raise ValueError('Refusing to replace a newer installation with an older release.')
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
    if previous_state is None and root==(home/'pet-tools/codex-whale-runtime').resolve():
        migrate_legacy(root,home)
        previous_state=state(root) if state_file(root).exists() else None
    home.mkdir(parents=True,exist_ok=True)
    root.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.whale-stage-',dir=home))
    tools=Path(tempfile.mkdtemp(prefix='.whale-tools-',dir=root.parent))
    pet=home/'pets/whale-musume'
    backup=None
    activated=False
    swapped=[]
    old_records={name:(root/name).read_bytes() if (root/name).exists() else None for name in ('assets-manifest.json','install-state.json',*COMMANDS)}
    if any(payload is not None and not payload.startswith(b'@rem Codex Whale Musume owned launcher') for name,payload in old_records.items() if name in COMMANDS):
        raise ValueError('An installed launcher was changed externally; no launcher was replaced.')
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
        for name,action in COMMANDS.items():
            atomic_bytes(root/name,('@rem Codex Whale Musume owned launcher\r\n@echo off\r\n"%~dp0runtime\\python.exe" "%~dp0app\\run.py" '+action+' %*\r\nif errorlevel 1 pause\r\n').encode('ascii'))
        bind(root,home)
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


def start(root,allow_untested=False,resuming=False,inline=False):
    record=state(root)
    home=Path(record['codex_home'])
    verify_assets(home/'pets/whale-musume',read_json(root/'assets-manifest.json'),live=True)
    if os.name!='nt':
        raise OSError('Enhanced native Pet control is supported on Windows only.')
    from .windows import check_version,controller_running
    version=check_version(allow_untested)
    if controller_running():
        return {'state':'already_running','codex_version':version,**check_running(root,home)}
    control=control_dir(home,create=True)
    if resuming and (control/'motion-stop').exists():
        return {'state':'paused'}
    if not resuming:
        (control/'motion-stop').unlink(missing_ok=True)
        (home/'pets/whale-musume/motion-stop').unlink(missing_ok=True)
        from .recovery import task
        if task(root,'query').get('registered',False):
            task(root,'run')
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:  # Wait for the owned scheduled task to acquire its controller mutex.
                if controller_running():
                    try:
                        return {'state':'started_by_scheduler',**check_running(root,home)}
                    except (FileNotFoundError,RuntimeError):
                        pass  # The mutex is acquired just before the new task writes its identity marker.
                if (control/'motion-stop').exists():
                    return {'state':'paused'}
                time.sleep(.1)
            raise RuntimeError('Scheduled controller did not start; inspect Doctor and recovery-status.json.')
    if inline:
        from .controller import run
        record['controller_started']=True
        atomic_json(state_file(root),record)
        with (root/'controller-error.log').open('a',encoding='utf-8') as errors:
            from contextlib import redirect_stderr
            with redirect_stderr(errors):
                run(home,allow_untested)
        return read_json(home/'pets/whale-musume/motion-status.json')
    log=root/'controller-error.log'
    command=[record['pythonw'],str(root/'app/run.py'),'run','--home',str(home)]
    if allow_untested:
        command.append('--allow-untested')
    with log.open('ab') as errors:
        if resuming and (control/'motion-stop').exists():
            return {'state':'paused'}
        if not resuming:
            (control/'motion-stop').unlink(missing_ok=True)
            (home/'pets/whale-musume/motion-stop').unlink(missing_ok=True)
        record['controller_started']=True
        atomic_json(state_file(root),record)
        process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=errors,
            creationflags=subprocess.CREATE_NO_WINDOW|subprocess.DETACHED_PROCESS)
    time.sleep(1)
    if resuming and (control/'motion-stop').exists():
        return {'state':'paused'}
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
            'pet_id':'whale-musume','motion_master':metadata['source_sha256'],'installation':runtime_identity(root)}
    path=home/'pets/whale-musume/motion-status.json'
    result['controller']=read_json(path) if path.exists() else {'state':'not_started'}
    if os.name=='nt':
        from .windows import APP_VERSION,TESTED_VERSIONS,controller_running,installed_version,selected_pet
        version=installed_version()
        result.update(codex_version=version,tested_codex_version=APP_VERSION,tested_codex_versions=TESTED_VERSIONS,version_tested=version in TESTED_VERSIONS,
                      whale_selected=selected_pet(home)=='custom:whale-musume')
        result['controller_running']=controller_running()
        if result['controller_running']:
            result['running_identity']=check_running(root,home)
        from .selection import migrated
        result['selection_source']='local' if result['whale_selected'] else 'migrated_cloud_whale' if migrated(home,selected_pet(home)) else 'other'
        local_mode=control_dir(home)/'local-mode.json'
        result['local_mode']=read_json(local_mode).get('state') if local_mode.exists() else 'not_configured'
        if not result['controller_running']:
            result['controller']={**result['controller'],'last_recorded_state':result['controller']['state'],'state':'not_running'}
        from .recovery import task
        result['recovery']=task(root,'query')
        recovery_status=control_dir(home)/'recovery-status.json'
        if recovery_status.exists():
            result['recovery']['last_attempt']=read_json(recovery_status)
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
    had_recovery=False
    if os.name=='nt':
        from .recovery import task
        from .selection import restore_migration_preferences
        from .windows import codex_processes
        had_recovery=task(root,'query').get('registered',False)
    stop(home,expect_running=bool(record.get('controller_started')))
    if had_recovery:
        task(root,'remove')
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
        for name in ('app','runtime','assets-manifest.json','controller-error.log','install-state.json',*COMMANDS):
            if (root/name).exists():
                os.replace(root/name,tools/name)
                moved.append(name)
        if os.name=='nt':
            restore_migration_preferences(home,lambda:not codex_processes())
    except Exception:
        for name in reversed(moved):
            os.replace(tools/name,root/name)
        if restored:
            os.replace(pet,original)
        if (pet_backup/'removed-pet').exists():
            os.replace(pet_backup/'removed-pet',pet)
        if had_recovery:
            task(root,'enable')
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
