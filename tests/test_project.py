import errno
import hashlib
import json
import math
import os
import random
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from codex_whale_pet import manage
from codex_whale_pet.behavior import FollowState,HoverState,direction,on_body,replay_webp
from codex_whale_pet.files import BASE,atomic_bytes,atomic_json,contained,control_dir,digest,read_json,verify_assets


def fixture(root):
    package=root/'source'
    pet=package/'pet'
    pet.mkdir(parents=True)
    (package/'app').mkdir()
    (package/'app/example.py').write_text('example = 1\n',encoding='utf-8')
    master=b'fixture master'
    (pet/'spritesheet.webp').write_bytes(master)
    (pet/BASE).write_bytes(b'fixture baseline')
    for index in range(16):
        path=pet/f'gaze-bank/v1/{index:02}.webp'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(bytes([index]))
    actions={}
    for name in ('hop','waving','eating'):
        path=pet/f'hover-bank/v1/{name}.webp'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(name.encode())
        actions[name]={'path':path.relative_to(pet).as_posix(),'sha256':digest(path),'hold_ms':3600 if name=='eating' else 2800}
    manifest={'id':'whale-musume','displayName':'Whale','description':'fixture','spriteVersionNumber':2,'spritesheetPath':BASE}
    atomic_json(pet/'pet.json',manifest)
    sha=hashlib.sha256(master).hexdigest()
    atomic_json(pet/'motion-assets.json',{'source_sha256':sha,'hover_source_sha256':sha,'bank':'gaze-bank/v1',
        'hover_actions':actions,'hover_live_path':'hover-bank/v1/active.webp','app_version':'26.1023.6621.0'})
    (pet/'LICENSE').write_text('fixture license',encoding='utf-8')
    checks={p.relative_to(pet).as_posix():{'bytes':p.stat().st_size,'sha256':digest(p)} for p in pet.rglob('*') if p.is_file()}
    atomic_json(package/'assets-manifest.json',{'schema':1,'pet_id':'whale-musume','pet_manifest':manifest,'files':checks})
    return package


class BehaviorTests(unittest.TestCase):
    def test_all_directions_and_negative_origins(self):
        center=(-1200,100)
        for index in range(16):
            angle=index*math.pi/8
            point=(center[0]+300*math.sin(angle),center[1]-300*math.cos(angle))
            self.assertEqual(direction(point,center,scale=1.5),index)

    def test_range_timeout_noise_and_reentry(self):
        state=FollowState()
        self.assertIsNone(state.update((700,0),(0,0),1,0))
        self.assertEqual(state.update((400,0),(0,0),1,.1),4)
        self.assertIsNone(state.update((400,0),(0,0),1,4.11))
        self.assertIsNone(state.update((400.5,0),(0,0),1,4.2))
        self.assertEqual(state.update((410,0),(0,0),1,4.3),4)
        self.assertEqual(state.update((525,0),(0,0),1,4.4),4)
        self.assertIsNone(state.update((551,0),(0,0),1,4.5))
        self.assertIsNone(state.update((525,0),(0,0),1,4.6))

    def test_random_rounds_and_no_repeat(self):
        actions={name:{'hold_ms':2800} for name in ('hop','waving','eating')}
        state=HoverState(actions,random.Random(12))
        self.assertIsNone(state.update(True,0))
        now=.07
        seen=[]
        for _ in range(12):
            action=state.update(True,now)
            seen.append(action)
            self.assertIsNone(state.update(True,now+2.801))
            self.assertIsNone(state.update(True,now+3.49))
            now+=3.52
        self.assertTrue(all(a!=b for a,b in zip(seen,seen[1:])))
        self.assertTrue(all(set(seen[index:index+3])==set(actions) for index in range(0,12,3)))
        self.assertIsNone(state.update(False,now))

    def test_hit_box_and_nonvisual_replay(self):
        layout={'center':(-100,100),'width_dip':112,'scale':1.5}
        self.assertFalse(on_body((-100+57*1.5,100),layout))
        self.assertTrue(on_body((-100+57*1.5,100),layout,6))
        source=b'RIFF'+(8).to_bytes(4,'little')+b'WEBPtest'
        first=replay_webp(source,'activation-a')
        second=replay_webp(source,'activation-b')
        self.assertNotEqual(first,second)
        self.assertEqual(first[8:len(source)],source[8:])
        self.assertEqual(int.from_bytes(first[4:8],'little'),len(first)-8)


class PackageTests(unittest.TestCase):
    def test_real_shipped_manifest_and_schema(self):
        manifest=read_json(ROOT/'assets-manifest.json')
        verify_assets(ROOT/'pet',manifest)
        self.assertEqual(manifest['pet_manifest']['displayName'],'鲸鱼娘')
        self.assertNotIn('name',manifest['pet_manifest'])
        self.assertEqual(manifest['pet_manifest']['spriteVersionNumber'],2)

    def test_traversal_and_missing_parent_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for name in ('../escape','C:/escape','x\\escape','/escape','a:stream'):
                with self.assertRaises(ValueError):contained(root,name)
            with self.assertRaises(FileNotFoundError):atomic_bytes(root/'missing/status.json',b'{}')


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='whale smoke space ')
        self.root=Path(self.temp.name).resolve()
        self.package=fixture(self.root)
        self.home=self.root/'home'
        self.install_root=self.root/'application'
        self.stop=mock.patch.object(manage,'stop')
        self.stop.start()

    def tearDown(self):
        self.stop.stop()
        self.temp.cleanup()

    def install(self):
        return manage.install(self.package,self.home,self.install_root,use_current_python=True)

    def seed_original(self):
        target=self.home/'pets/whale-musume'
        target.mkdir(parents=True)
        (target/'original.txt').write_text('original pet',encoding='utf-8')
        (self.home/'pets/another').mkdir()
        (self.home/'pets/another/keep.txt').write_text('another pet',encoding='utf-8')
        (self.home/'config.toml').write_text('[private_fixture]\nvalue = "retain"\n',encoding='utf-8')

    def test_fresh_install_live_manifest_doctor_and_uninstall(self):
        self.install()
        pet=self.home/'pets/whale-musume'
        current=read_json(pet/'pet.json')
        current['spritesheetPath']='gaze-bank/v1/00.webp'
        atomic_json(pet/'pet.json',current)
        with mock.patch.dict(sys.modules,{}):
            verify_assets(pet,read_json(self.install_root/'assets-manifest.json'),live=True)
        result=manage.uninstall(self.install_root)
        self.assertFalse(result['previous_pet_restored'])
        self.assertFalse(pet.exists())

    def test_upgrade_then_uninstall_restores_original_and_keeps_other_data(self):
        self.seed_original()
        before=(self.home/'config.toml').read_bytes()
        first=self.install()
        second=self.install()
        self.assertEqual(first['original_backup'],second['original_backup'])
        (self.install_root/'user-note.txt').write_text('retain',encoding='utf-8')
        result=manage.uninstall(self.install_root)
        self.assertTrue(result['previous_pet_restored'])
        self.assertEqual((self.home/'pets/whale-musume/original.txt').read_text(),'original pet')
        self.assertTrue((self.home/'pets/another/keep.txt').exists())
        self.assertEqual((self.home/'config.toml').read_bytes(),before)
        self.assertTrue((self.install_root/'user-note.txt').exists())

    def test_changed_home_refused_before_writes(self):
        self.install()
        old=read_json(manage.state_file(self.install_root))
        with self.assertRaises(ValueError):manage.install(self.package,self.root/'other-home',self.install_root,True)
        self.assertEqual(read_json(manage.state_file(self.install_root)),old)
        self.assertFalse((self.root/'other-home').exists())

    def test_unowned_install_directory_refused(self):
        self.install_root.mkdir()
        (self.install_root/'keep.txt').write_text('retain')
        with self.assertRaises(ValueError):self.install()
        self.assertTrue((self.install_root/'keep.txt').exists())

    def test_corrupt_asset_never_activates(self):
        (self.package/'pet/spritesheet.webp').write_bytes(b'corrupt')
        with self.assertRaises(ValueError):self.install()
        self.assertFalse((self.home/'pets/whale-musume').exists())

    def test_failed_upgrade_commit_restores_old_install(self):
        self.seed_original()
        old=self.install()
        original=manage.atomic_json
        def fail_commit(path,value):
            if path.resolve()==manage.state_file(self.install_root).resolve():raise OSError('injected commit failure')
            original(path,value)
        with mock.patch.object(manage,'atomic_json',side_effect=fail_commit):
            with self.assertRaises(OSError):self.install()
        self.assertEqual(read_json(manage.state_file(self.install_root)),old)
        verify_assets(self.home/'pets/whale-musume',read_json(self.install_root/'assets-manifest.json'),live=True)

    def test_uninstall_restore_failure_rolls_back_and_can_retry(self):
        self.seed_original()
        record=self.install()
        original=manage.os.replace
        def fail_restore(source,target):
            if Path(source)==Path(record['original_backup']):raise PermissionError('injected restore failure')
            return original(source,target)
        with mock.patch.object(manage.os,'replace',side_effect=fail_restore):
            with self.assertRaises(PermissionError):manage.uninstall(self.install_root)
        self.assertEqual(read_json(manage.state_file(self.install_root)),record)
        self.assertTrue((self.home/'pets/whale-musume/.codex-whale-owner.json').exists())
        self.assertTrue(manage.uninstall(self.install_root)['previous_pet_restored'])


@unittest.skipUnless(os.name=='nt','Windows pipe integration')
class WindowsBoundaryTests(unittest.TestCase):
    def test_missing_pipe_and_permission_boundary(self):
        from codex_whale_pet import windows as win
        with mock.patch('builtins.open',side_effect=FileNotFoundError(errno.ENOENT,'missing')):
            with self.assertRaises(win.NotReady):win.PetRefresh()
        with mock.patch('builtins.open',side_effect=PermissionError(errno.EACCES,'denied')):
            with self.assertRaises(PermissionError):win.PetRefresh()

    def test_errno22_requires_confirmed_disconnect(self):
        from codex_whale_pet import windows as win
        peer=win.PetRefresh.__new__(win.PetRefresh)
        peer.pipe=mock.Mock()
        peer.pipe.write.side_effect=OSError(errno.EINVAL,'invalid')
        peer.handle=0
        def disconnected(*args):
            win.ct.set_last_error(109)
            return False
        message={'method':'initialize'}
        with mock.patch.object(win.kernel,'PeekNamedPipe',side_effect=disconnected):
            with self.assertRaises(win.NotReady):peer.send(message)
        with mock.patch.object(win.kernel,'PeekNamedPipe',return_value=True):
            with self.assertRaises(OSError):peer.send(message)

    def test_stop_marker_survives_pet_swap_and_no_status_waits(self):
        from codex_whale_pet import windows as win
        with tempfile.TemporaryDirectory() as temporary:
            home=Path(temporary)
            pet=home/'pets/whale-musume'
            pet.mkdir(parents=True)
            with mock.patch.object(win,'controller_running',side_effect=[True,False,False]) as running:
                manage.stop(home)
            self.assertGreater(running.call_count,0)
            shutil.move(pet,home/'old-pet')
            pet.mkdir()
            self.assertTrue((control_dir(home)/'motion-stop').exists())


if __name__=='__main__':unittest.main()
