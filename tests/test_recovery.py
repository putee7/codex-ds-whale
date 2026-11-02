import os
import sys
import tempfile
import itertools
import shutil
import unittest
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from codex_whale_pet import manage,recovery,selection
from codex_whale_pet.files import OWNER,PET_ID,atomic_bytes,atomic_json,control_dir,read_json


class TaskTests(unittest.TestCase):
    def test_task_has_no_elevation_and_uses_quoted_installed_entrypoint(self):
        root=Path(tempfile.gettempdir())/'whale space & bracket [test]'
        record={'pythonw':str(root/'runtime/pythonw.exe'),'install_root':str(root)}
        xml=ET.fromstring(recovery.task_xml(record))
        ns={'t':recovery.NS}
        self.assertEqual(xml.findtext('t:RegistrationInfo/t:Description',namespaces=ns),OWNER)
        self.assertEqual(xml.findtext('.//t:RunLevel',namespaces=ns),'LeastPrivilege')
        self.assertEqual(xml.findtext('.//t:LogonType',namespaces=ns),'InteractiveToken')
        self.assertEqual(xml.findtext('.//t:Interval',namespaces=ns),'PT1M')
        self.assertEqual(xml.findtext('.//t:ExecutionTimeLimit',namespaces=ns),'PT0S')
        self.assertIn('"'+str(root/'app/run.py')+'"',xml.findtext('.//t:Arguments',namespaces=ns))
        self.assertIn('resume',xml.findtext('.//t:Arguments',namespaces=ns))

    @unittest.skipUnless(os.name=='nt','Windows recovery')
    def test_stop_marker_prevents_task_restart_then_start_can_resume(self):
        from codex_whale_pet import windows as win
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            home=root/'home'
            control=control_dir(home,True)
            atomic_bytes(control/'motion-stop',b'')
            with mock.patch.object(manage,'state',return_value={'codex_home':str(home)}), \
                 mock.patch.object(win,'controller_running',return_value=False), \
                 mock.patch.object(manage,'start',return_value={'state':'running'}) as start:
                self.assertEqual(recovery.resume(root)['state'],'paused')
                start.assert_not_called()
                (control/'motion-stop').unlink()
                self.assertEqual(recovery.resume(root)['state'],'running')
                start.assert_called_once_with(root,resuming=True,inline=True)

    @unittest.skipUnless(os.name=='nt','Windows recovery')
    def test_live_controller_is_not_restarted_and_failures_are_visible(self):
        from codex_whale_pet import windows as win
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            home=root/'home'
            with mock.patch.object(manage,'state',return_value={'codex_home':str(home)}), \
                 mock.patch.object(win,'controller_running',return_value=True), \
                 mock.patch.object(manage,'check_running',return_value={}), \
                 mock.patch.object(manage,'start') as start:
                self.assertEqual(recovery.resume(root)['state'],'already_running')
                start.assert_not_called()
            with mock.patch.object(manage,'state',return_value={'codex_home':str(home)}), \
                 mock.patch.object(win,'controller_running',return_value=False), \
                 mock.patch.object(manage,'start',side_effect=PermissionError('injected')):
                with self.assertRaises(PermissionError):recovery.resume(root)
                self.assertEqual(read_json(control_dir(home)/'recovery-status.json')['state'],'error')

    @unittest.skipUnless(os.name=='nt','Windows compatibility')
    def test_new_version_not_rejected_only_by_number(self):
        from codex_whale_pet import windows as win
        with mock.patch.object(win,'installed_version',return_value='26.1111.1.0'):
            self.assertEqual(win.check_version(),'26.1111.1.0')
        with mock.patch.object(win,'installed_version',return_value=None):
            with self.assertRaises(win.NotReady):win.check_version()

    @unittest.skipUnless(os.name=='nt','Windows recovery')
    def test_late_stop_is_never_cleared_by_resume_start(self):
        from codex_whale_pet import windows as win
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            home=root/'home'
            flag=control_dir(home,True)/'motion-stop'
            atomic_bytes(flag,b'')
            atomic_json(root/'assets-manifest.json',{})
            record={'codex_home':str(home),'pythonw':'unused'}
            with mock.patch.object(manage,'state',return_value=record), \
                 mock.patch.object(manage,'verify_assets'), \
                 mock.patch.object(win,'check_version',return_value='new'), \
                 mock.patch.object(win,'controller_running',return_value=False), \
                 mock.patch.object(manage.subprocess,'Popen') as spawn:
                self.assertEqual(manage.start(root,resuming=True)['state'],'paused')
                self.assertTrue(flag.exists())
                spawn.assert_not_called()



if __name__=='__main__':unittest.main()
