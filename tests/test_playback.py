"""Clock-driven regressions for the optional local animation bank."""
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from codex_whale_pet.behavior import HoverState
from codex_whale_pet.playback import Playback


class PlaybackTests(unittest.TestCase):
    def setUp(self):
        self.player=Playback({'clips':{key:{'hold_ms':ms} for key,ms in {
            'think':2000,'deep-think':2000,'wait':2000,'celebrate':3000,
            'sleep-in':4000,'sleep-loop':10000,'sleep-out':3000,'yawn':5000,
        }.items()},'rotation':{'thinking':['think','deep-think'],'waiting':['wait'],
                            'success':['celebrate'],'idle':['yawn']}})

    def test_work_rotates_with_original_breathing_pose_between_clips(self):
        self.assertIsNone(self.player.update('thinking',0))
        self.assertEqual(self.player.update('thinking',1.31),'think')
        self.assertIsNone(self.player.update('thinking',3.32))
        self.assertEqual(self.player.update('thinking',6.13),'deep-think')
        self.assertIsNone(self.player.update('waiting',6.15))
        self.assertEqual(self.player.update('waiting',6.51),'wait')
        self.assertIsNone(self.player.update('editing',6.52))

    def test_sleep_enters_once_then_loops_and_wakes_without_restarting(self):
        self.assertEqual(self.player.update('sleep',600),'sleep-in')
        self.assertEqual(self.player.update('sleep',603.9),'sleep-in')
        self.assertEqual(self.player.update('sleep',604),'sleep-loop')
        self.assertEqual(self.player.update('sleep',700),'sleep-loop')
        self.assertEqual(self.player.update('idle',701),'sleep-out')
        self.assertEqual(self.player.update('idle',703.9,suppressed=True),'sleep-out')
        self.assertIsNone(self.player.update('idle',704,suppressed=True))

    def test_approval_cancels_sleep_without_delaying_status(self):
        self.player.update('sleep',600)
        self.assertIsNone(self.player.update('waiting',601))
        self.assertEqual(self.player.update('waiting',601.4),'wait')
        self.assertIsNone(self.player.update('idle',602))

    def test_quiet_idle_and_terminal_preemption(self):
        self.assertIsNone(self.player.update('idle',0))
        self.assertIsNone(self.player.update('idle',60,idle_allowed=False))
        self.assertIsNone(self.player.update('idle',119))
        self.assertEqual(self.player.update('idle',120),'yawn')
        self.assertIsNone(self.player.update('idle',121,suppressed=True))
        self.assertIsNone(self.player.update('success',122))
        self.assertEqual(self.player.update('success',122.4),'celebrate')
        self.assertEqual(self.player.update('idle',124,idle_allowed=False),'celebrate')
        self.assertIsNone(self.player.update('thinking',124.1))

    def test_sleep_is_interrupted_immediately_by_active_work(self):
        self.player.update('sleep',600)
        self.assertIsNone(self.player.update('thinking',601))
        self.assertEqual(self.player.update('thinking',602.4),'think')

    def test_early_hover_keeps_original_triplet_and_expands_later_rounds(self):
        original={key:{'hold_ms':1000} for key in ('hop','waving','eating')}
        extra={key:{'hold_ms':1000} for key in ('shy','tickle')}
        hover=HoverState(original,random.Random(2),extra)
        hover.update(True,0)
        selected=[]
        for i in range(8):
            now=.1+i*2
            selected.append(hover.update(True,now))
            hover.update(True,now+1.1)
        self.assertEqual(set(selected[:3]),set(original))
        self.assertEqual(set(selected[4:7]),set(original))
        self.assertEqual({selected[3],selected[7]},set(extra))
        self.assertIsNone(hover.update(False,16))


if __name__=='__main__':
    unittest.main()
