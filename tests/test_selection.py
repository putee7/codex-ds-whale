import copy
import json
import itertools
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from contextlib import contextmanager

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from codex_whale_pet import manage,selection
from codex_whale_pet.files import PET_ID,atomic_json,control_dir,read_json


class LocalModeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name)
        self.value={'unrelated':{'untouched-user-data':[1,2,3]},'electron-persisted-atom-state':{
            selection.MIGRATED:{'account':{PET_ID:'pet_example','custom:other':'pet_other'}},
            selection.PENDING:{'account':{'custom:other':{'failedPermanently':False}}},
            selection.OBSERVED:{'account':'pet_example'},'other-preference':42}}
        self.state=self.home/'.codex-global-state.json'
        atomic_json(self.state,self.value)
        self.config=self.home/'config.toml'
        self.config.write_bytes(b'\xef\xbb\xbf# retained\r\n[desktop]\r\nselected-avatar-id = "pet_example" # retained\r\nother = true\r\n[another]\r\nvalue="unchanged"\r\n')

    def test_live_app_is_never_repaired_on_disk_and_later_manual_choice_wins(self):
        original=self.state.read_bytes()
        selection.request(self.home,'pet_example')
        self.assertIsNone(selection.maintain(self.home,lambda:False))
        self.assertEqual(original,self.state.read_bytes())
        self.config.write_text('[desktop]\nselected-avatar-id="codex"\n')
        selection.maintain(self.home,lambda:True)
        self.assertIn('"codex"',self.config.read_text())

    def test_restart_repair_retains_other_pets_data_and_cloud_selection(self):
        original=self.config.read_bytes()
        selection.request(self.home,'pet_example')
        result=selection.maintain(self.home,lambda:True)
        self.assertEqual(result['changed_files'],2)
        expected=copy.deepcopy(self.value)
        atoms=expected['electron-persisted-atom-state']
        del atoms[selection.MIGRATED]['account'][PET_ID]
        atoms[selection.PENDING]['account'][PET_ID]={'failedPermanently':True}
        self.assertEqual(read_json(self.state),expected)
        self.assertEqual(self.config.read_bytes(),original.replace(b'pet_example',PET_ID.encode()))
        self.assertFalse(selection.migrated(self.home,'pet_example'))
        record=control_dir(self.home)/'local-mode.json'
        stamp=record.stat().st_mtime_ns
        self.assertEqual(selection.maintain(self.home,lambda:True)['changed_files'],0)
        self.assertEqual(stamp,record.stat().st_mtime_ns)

    def test_codex_starting_during_commit_rolls_back_and_retains_request(self):
        originals=(self.state.read_bytes(),self.config.read_bytes())
        selection.request(self.home,'pet_example')
        with self.assertRaises(RuntimeError):
            selection.maintain(self.home,mock.Mock(side_effect=[True,True,False]))
        self.assertEqual((self.state.read_bytes(),self.config.read_bytes()),originals)
        self.assertEqual(read_json(control_dir(self.home)/'local-mode.json')['state'],'pending_codex_exit')

    def test_unknown_preference_format_fails_without_writes(self):
        atomic_json(self.state,{'electron-persisted-atom-state':{selection.MIGRATED:[]}})
        original=self.state.read_bytes()
        selection.request(self.home,'pet_example')
        with self.assertRaises(ValueError):selection.maintain(self.home,lambda:True)
        self.assertEqual(self.state.read_bytes(),original)

    def test_cloud_whale_is_identified_before_repair(self):
        self.assertTrue(selection.migrated(self.home,'pet_example'))
        self.assertFalse(selection.migrated(self.home,'pet_other'))

    def test_uninstall_restores_only_owned_migration_changes(self):
        selection.request(self.home,'pet_example')
        selection.maintain(self.home,lambda:True)
        current=read_json(self.state)
        current['unrelated']['new-user-choice']=99
        atomic_json(self.state,current)
        with self.assertRaises(RuntimeError):selection.restore_migration_preferences(self.home,lambda:False)
        selection.restore_migration_preferences(self.home,lambda:True)
        expected=copy.deepcopy(self.value)
        expected['unrelated']['new-user-choice']=99
        self.assertEqual(read_json(self.state),expected)

    def test_install_root_does_not_depend_on_msix_appdata_environment(self):
        with mock.patch.dict('os.environ',{'LOCALAPPDATA':'unrelated-package-cache'}):
            self.assertEqual(manage.default_install(self.home),self.home/'pet-tools/codex-whale-runtime')

    def test_one_binding_rejects_a_second_install_root(self):
        canonical=manage.default_install(self.home)
        manage.bind(canonical,self.home)
        self.assertEqual(manage.default_install(self.home),canonical)
        with self.assertRaisesRegex(ValueError,'canonical installation'):
            manage.install(self.home/'source',self.home,self.home/'other-root')

    def test_legacy_upgrade_moves_runtime_and_rebinds_without_a_copy(self):
        local=self.home/'local'
        old=local/'CodexWhaleMusume'
        old.mkdir(parents=True)
        (old/'runtime').mkdir()
        (old/'runtime/pythonw.exe').write_bytes(b'fixture runtime')
        atomic_json(old/'install-state.json',{'owner':manage.OWNER,'version':'1.0.2','install_root':str(old),
            'codex_home':str(self.home),'python':str(old/'runtime/python.exe'),'pythonw':str(old/'runtime/pythonw.exe')})
        root=manage.default_install(self.home)
        with mock.patch.dict('os.environ',{'LOCALAPPDATA':str(local)}), \
             mock.patch.object(manage,'stop'), \
             mock.patch('codex_whale_pet.recovery.task',return_value={'registered':True}) as task:
            manage.migrate_legacy(root,self.home)
        self.assertFalse(old.exists())
        self.assertEqual((root/'runtime/pythonw.exe').read_bytes(),b'fixture runtime')
        self.assertEqual(manage.default_install(self.home),root)
        self.assertEqual(manage.state(root)['pythonw'],str(root/'runtime/pythonw.exe'))
        self.assertEqual([call.args[1] for call in task.call_args_list],['query','remove'])

    @unittest.skipUnless(sys.platform=='win32','Windows process identity')
    def test_same_version_from_another_path_is_rejected(self):
        from codex_whale_pet import windows
        root=self.home/'application'
        root.mkdir()
        (root/'app').mkdir()
        (root/'app/run.py').write_text('example=1')
        atomic_json(root/'install-state.json',{'owner':manage.OWNER,'version':'1.1.0','install_root':str(root),'pythonw':str(root/'runtime/pythonw.exe')})
        identity=manage.runtime_identity(root)
        atomic_json(control_dir(self.home,True)/'started.json',{**identity,'pid':123})
        with mock.patch.object(windows,'app_path',return_value=str(self.home/'old/pythonw.exe')):
            with self.assertRaisesRegex(RuntimeError,'another path or build'):manage.check_running(root,self.home)

    @unittest.skipUnless(sys.platform=='win32','Windows controller')
    def test_closed_app_maintenance_reconnects_to_same_local_pet(self):
        from test_project import fixture
        from codex_whale_pet import controller,windows as win
        package=fixture(self.home/'scenario')
        (self.home/'pets').mkdir()
        shutil.copytree(package/'pet',self.home/'pets/whale-musume')
        selection.request(self.home,'pet_example')
        @contextmanager
        def acquired():yield True
        peer=mock.Mock()
        def cursor():
            (control_dir(self.home)/'motion-stop').touch()
            return 900,900
        with mock.patch.object(win,'single_controller',side_effect=acquired), \
             mock.patch.object(win,'running_version',side_effect=[win.NotReady('closed'),'new']), \
             mock.patch.object(win,'codex_processes',return_value=[]), \
             mock.patch.object(win,'PetRefresh',return_value=peer), \
             mock.patch.object(win,'geometry',return_value={'version':'new','center':(0,0),'scale':1,'width_dip':112}), \
             mock.patch.object(win.user,'GetAsyncKeyState',return_value=0), \
             mock.patch.object(win,'cursor',side_effect=cursor), \
             mock.patch.object(controller.time,'monotonic',side_effect=itertools.count(10,3)), \
             mock.patch.object(controller.time,'sleep'):
            controller.run(self.home)
        self.assertEqual(win.selected_pet(self.home),PET_ID)
        self.assertEqual(read_json(control_dir(self.home)/'local-mode.json')['state'],'applied')
        self.assertEqual(read_json(self.home/'pets/whale-musume/motion-status.json')['state'],'stopped')


if __name__=='__main__':unittest.main()
