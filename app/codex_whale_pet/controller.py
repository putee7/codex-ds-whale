"""One headless controller updates only the existing local Pet's data assets."""
import os
import time
import uuid

from .behavior import FollowState, HoverState, on_body, replay_webp
from .files import BASE, PET_ID, OWNER, atomic_bytes, atomic_json, contained, control_dir, digest, read_json


def run(home, allow_untested=False):
    from . import windows as win
    control=control_dir(home,create=True)
    stop_path=control/'motion-stop'
    atomic_json(control/'started.json',{'owner':OWNER,'pid':os.getpid()})
    if stop_path.exists():
        return
    folder=home/'pets/whale-musume'
    metadata=read_json(folder/'motion-assets.json')
    if digest(folder/'spritesheet.webp')!=metadata['source_sha256']:
        raise ValueError('Pet artwork changed; rebuild the motion assets before starting.')
    actions=metadata['hover_actions']
    templates={name:contained(folder,value['path'],True).read_bytes() for name,value in actions.items()}
    if any(digest(contained(folder,value['path'],True))!=value['sha256'] for value in actions.values()):
        raise ValueError('A hover template was changed.')
    live=metadata['hover_live_path']
    live_path=contained(folder,live)
    bank=metadata['bank']
    owned={BASE,live,*(f'{bank}/{index:02}.webp' for index in range(16))}
    manifest_path=folder/'pet.json'
    expected={key:value for key,value in read_json(manifest_path).items() if key!='spritesheetPath'}
    status_path=folder/'motion-status.json'
    source_mtime=(folder/'spritesheet.webp').stat().st_mtime_ns
    ipc=None
    active_path=read_json(manifest_path)['spritesheetPath']
    follow,hover=FollowState(),HoverState(actions)
    changes,last_write,last_mode,last_check,last_geometry_check,last_click,last_switch=0,0.,None,0.,0.,0.,0.
    layout,last_action=None,None

    def status(state,reason=None,force=False):
        nonlocal last_mode,last_write
        mode=(state,reason,hover.current,active_path,changes)
        if force or mode!=last_mode or time.monotonic()-last_write>=10:
            atomic_json(status_path,{'state':state,'reason':reason,'pid':os.getpid(),
                'updated_at':time.strftime('%Y-%m-%dT%H:%M:%S'),'direction':follow.previous,
                'gaze_mode':('hover' if hover.current else 'hover_rest') if hover.inside else follow.reason,
                'hover_action':hover.current,'active_asset':active_path,'asset_changes':changes,
                'range_dip':500,'idle_seconds':4,'native_window_only':True,'client_files_modified':False,
                'allow_untested':allow_untested})
            last_mode,last_write=mode,time.monotonic()

    def switch(path,force=False):
        nonlocal active_path,changes
        current=read_json(manifest_path)
        if {key:value for key,value in current.items() if key!='spritesheetPath'}!=expected or current['spritesheetPath'] not in owned:
            raise ValueError('Pet manifest was edited externally; controller stopped without replacing it.')
        if current['spritesheetPath']!=path:
            contained(folder,path,True)
            current['spritesheetPath']=path
            atomic_json(manifest_path,current)
            active_path=path
            changes+=1
            if ipc:
                ipc.refresh()
        elif force and ipc:
            ipc.refresh()

    with win.single_controller() as acquired:
        if not acquired:
            return
        if stop_path.exists():
            return
        status('starting',force=True)
        try:
            if stop_path.exists():
                status('stopped','Stop requested during startup.',True)
                return
            switch(BASE)
            while not stop_path.exists():  # Windows cursor and native availability require a bounded polling loop.
                try:
                    if ipc is None:
                        ipc=win.PetRefresh()
                        ipc.refresh()
                    ipc.pump()
                    now=time.monotonic()
                    if now-last_check>=.5:
                        if (folder/'spritesheet.webp').stat().st_mtime_ns!=source_mtime:
                            raise ValueError('Artwork changed; rebuild assets instead of overwriting active files.')
                        last_check=now
                    if win.selected_pet(home)!=PET_ID:
                        switch(BASE)
                        follow,hover=FollowState(),HoverState(actions)
                        status('waiting_for_selection','Select the whale in Codex Settings > Mini and pets.')
                        time.sleep(.5)
                        continue
                    if win.user.GetAsyncKeyState(1)&0x8000:
                        last_click=now
                        time.sleep(.06)
                        continue
                    if now-last_click<.15:
                        time.sleep(.06)
                        continue
                    if layout is None or now-last_geometry_check>=.4:
                        layout=win.geometry(home,allow_untested)
                        last_geometry_check=now
                    point=win.cursor()
                    target=follow.update(point,layout['center'],layout['scale'],now)
                    action=hover.update(on_body(point,layout,6 if hover.inside else 0),now)
                    path=live if action else BASE if hover.inside or target is None else f'{bank}/{target:02}.webp'
                    triggered=action is not None and action!=last_action
                    if (path!=active_path or triggered) and now-last_switch>=.12:
                        if triggered:
                            atomic_bytes(live_path,replay_webp(templates[action],uuid.uuid4().hex))
                        switch(path,triggered)
                        last_switch,last_action=now,action
                    if action is None:
                        last_action=None
                    status('running')
                    time.sleep(.06)
                except win.NotReady as error:
                    if ipc:
                        ipc.close()
                        ipc=None
                    switch(BASE)
                    layout,last_action=None,None
                    follow,hover=FollowState(),HoverState(actions)
                    status('waiting',str(error))
                    time.sleep(.5)
            status('stopped','Stop requested.',True)
        except Exception as error:
            status('error',str(error),True)
            raise
        finally:
            current=read_json(manifest_path)
            if current.get('spritesheetPath') in owned:
                current['spritesheetPath']=BASE
                atomic_json(manifest_path,current)
                if ipc:
                    try:
                        ipc.refresh()
                    except (OSError,win.NotReady):
                        pass  # The status already names the disconnect; a closed app cannot receive a notification.
            if ipc:
                ipc.close()
