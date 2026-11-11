"""Real snapshot/Immer shapes, redaction, ordering and lifecycle regressions."""
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from codex_whale_pet.activity import Activity,ActivityView,project,recent_threads,tool_mode


def snapshot(items=None,status='inProgress',revision=1,started=1000,requests=None):
    return {'type':'snapshot','revision':revision,'conversationState':{
        'title':'PRIVATE_TITLE','requests':requests or [],'threadRuntimeStatus':{'type':'active' if status=='inProgress' else 'idle'},
        'turnHistory':{'history':{'entitiesByKey':{'turn-key':{'turnId':'turn','status':status,'turnStartedAtMs':started,
            'params':{'input':'PRIVATE_PROMPT'},'items':items or []}}}}}}


def patch(path,value,revision=2,base=1,op='replace'):
    return {'type':'patches','baseRevision':base,'revision':revision,'patches':[{'op':op,'path':path,'value':value}]}


PREFIX=['turnHistory','history','entitiesByKey','turn-key']


class ActivityTests(unittest.TestCase):
    def test_each_tool_category_and_quoted_text_is_not_a_command(self):
        commands={'python -m unittest discover':'testing','pytest tests':'testing','git diff':'reviewing',
            'gh release create v2':'deploying','kubectl apply -f app.yaml':'deploying','python -m pdb app.py':'debugging',
            'rg --files':'searching','Get-Content file.txt':'searching','git status':'command','echo "pytest deploy"':'command'}
        for command,mode in commands.items():
            self.assertEqual(tool_mode({'type':'commandExecution','command':command}),mode)
        for kind,mode in [('fileChange','editing'),('webSearch','searching'),('imageGeneration','working')]:
            self.assertEqual(tool_mode({'type':kind}),mode)
        self.assertEqual(tool_mode({'type':'mcpToolCall','tool':'update_plan'}),'planning')

    def test_projection_discards_prompts_outputs_commands_and_configuration(self):
        data=snapshot([{'type':'commandExecution','id':'tool','status':'inProgress','command':'pytest "PRIVATE_ARGUMENT"',
            'aggregatedOutput':'PRIVATE_OUTPUT','cwd':'PRIVATE_DIRECTORY','startedAtMs':20}])
        view=ActivityView()
        view.accept(data,'owner',0)
        self.assertEqual(view.mode,'testing')
        self.assertNotIn('PRIVATE',json.dumps(view.state))
        view.accept(patch(PREFIX+['items',0],{'type':'mcpToolCall','tool':'secret_unknown_tool','arguments':'PRIVATE_ARGS',
            'result':'PRIVATE_RESULT','status':'inProgress','startedAtMs':22}),'owner',1)
        self.assertEqual(view.mode,'working')
        self.assertEqual(view.reason,'active_tool:mcpToolCall')
        self.assertNotIn('PRIVATE',json.dumps(view.state))
        self.assertNotIn('secret_unknown_tool',json.dumps(view.state))

    def test_thinking_tools_completion_and_no_historical_success_on_start(self):
        view=ActivityView()
        view.accept(snapshot([{'type':'reasoning','startedAtMs':2}]),'owner',0)
        self.assertEqual(view.mode,'thinking')
        view.accept(patch(PREFIX+['items',1],{'type':'fileChange','status':'inProgress','startedAtMs':3},op='add'),'owner',1)
        self.assertEqual(view.mode,'editing')
        view.accept(patch(PREFIX+['items',2],{'type':'reasoning','startedAtMs':4},revision=3,base=2,op='add'),'owner',2)
        self.assertEqual(view.mode,'thinking')  # An older background command cannot pin every later request to work.
        view.accept(snapshot(status='completed',revision=4),'owner',3)
        self.assertEqual(view.mode,'success')
        view.derive(5.01)
        self.assertEqual(view.mode,'idle')
        cold=ActivityView()
        cold.accept(snapshot(status='completed'),'owner',0)
        self.assertEqual(cold.mode,'idle')

    def test_pending_requests_remove_and_native_array_replacement(self):
        view=ActivityView()
        view.accept(snapshot(requests=[{'type':'approval','prompt':'PRIVATE'}]),'owner',0)
        self.assertEqual(view.mode,'waiting')
        view.accept(patch(['requests',0],None,op='remove'),'owner',1)
        self.assertNotEqual(view.mode,'waiting')
        view.accept(patch(PREFIX+['items'],[{'type':'webSearch','status':'inProgress','startedAtMs':30}],3,2),'owner',2)
        self.assertEqual(view.mode,'searching')
        view.accept(patch(PREFIX+['items',0],None,4,3,op='remove'),'owner',3)
        self.assertEqual(view.state['turnHistory']['history']['entitiesByKey']['turn-key']['items'],[])
        self.assertEqual(view.mode,'thinking')

    def test_failure_window_and_revision_gap(self):
        view=ActivityView()
        view.accept(snapshot(),'owner',0)
        view.accept(snapshot(status='failed',revision=2),'owner',1)
        self.assertEqual(view.mode,'failure')
        view.derive(4.01)
        self.assertEqual(view.mode,'idle')
        with self.assertRaisesRegex(ValueError,'revision gap'):
            view.accept(patch(PREFIX+['status'],'completed',4,1),'owner',5)

    def test_tool_error_is_finite_and_new_work_can_continue(self):
        view=ActivityView()
        view.accept(snapshot([{'type':'mcpToolCall','id':'tool','status':'failed','startedAtMs':5}]),'owner',0)
        self.assertEqual(view.mode,'failure')
        view.derive(2.01)
        self.assertEqual(view.mode,'thinking')
        view.accept(patch(PREFIX+['items',1],{'type':'fileChange','status':'inProgress','startedAtMs':6},op='add'),'owner',3)
        self.assertEqual(view.mode,'editing')

    def test_discovery_resync_and_no_stuck_work_after_owner_disconnect(self):
        activity=Activity()
        activity.discover([('local','thread')])
        self.assertEqual(activity.subscriptions(),[('local','thread')])
        message={'type':'broadcast','method':'thread-stream-state-changed','version':11,'sourceClientId':'owner',
            'params':{'hostId':'local','conversationId':'thread','change':snapshot([{'type':'reasoning'}])}}
        activity.receive(message,'self',0)
        activity.update(0)
        self.assertEqual(activity.update(.3),'thinking')
        activity.receive({**message,'params':{**message['params'],'change':patch(PREFIX+['status'],'completed',3,0)}},'self',1)
        self.assertIn('revision gap',activity.error)
        self.assertEqual(activity.subscriptions(),[('local','thread')])
        activity.receive(message,'self',2)
        self.assertIsNone(activity.error)
        activity.receive({'method':'client-status-changed','params':{'clientId':'owner','status':'disconnected'}},'self',3)
        activity.update(3)
        self.assertEqual(activity.update(3.3),'idle')

    def test_newest_active_thread_beats_an_old_terminal_or_historical_turn(self):
        activity=Activity()
        activity.discover([('local','old'),('local','new')])
        activity.subscriptions()
        for name,started,kind in [('old',10,'webSearch'),('new',20,'fileChange')]:
            activity.receive({'method':'thread-stream-state-changed','version':11,'sourceClientId':'owner',
                'params':{'hostId':'local','conversationId':name,'change':snapshot([{'type':kind,'status':'inProgress'}],started=started)}},'self',0)
        activity.update(0)
        self.assertEqual(activity.update(.3),'editing')

    def test_pending_approval_in_older_thread_takes_priority(self):
        activity=Activity()
        older,newer=ActivityView(),ActivityView()
        older.accept(snapshot(started=10,requests=[{'type':'approval'}]),'owner',0)
        newer.accept(snapshot(started=20),'owner',0)
        activity.views={'old':older,'new':newer}
        self.assertEqual(activity.update(0),'waiting')
        older.accept(patch(['requests',0],None,op='remove'),'owner',1)
        activity.update(1)
        self.assertEqual(activity.update(1.3),'thinking')

    def test_readonly_discovery_ignores_backups_and_respects_archived(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp)
            with closing(sqlite3.connect(home/'state_5.sqlite')) as db:
                db.execute('CREATE TABLE threads(id TEXT, archived INTEGER, updated_at INTEGER, title TEXT)')
                db.executemany('INSERT INTO threads VALUES(?,?,?,?)',[('old',0,1,'PRIVATE'),('new',0,2,'PRIVATE'),('archived',1,3,'PRIVATE')])
                db.commit()
            (home/'state_99.backup.sqlite').write_bytes(b'invalid backup')
            before=(home/'state_5.sqlite').read_bytes()
            self.assertEqual(recent_threads(home),[('local','new'),('local','old')])
            self.assertEqual((home/'state_5.sqlite').read_bytes(),before)


if __name__=='__main__':unittest.main()
