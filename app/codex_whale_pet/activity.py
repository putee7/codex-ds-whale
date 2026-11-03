"""Project live IPC state to content-free activity metadata, never a transcript mirror."""
import re
import sqlite3
import time
from contextlib import closing

SKIP=object()
TURN_FIELDS={'turnId','status','turnStartedAtMs','durationMs'}
ITEM_FIELDS={'id','type','status','startedAtMs','completedAtMs'}
TOOLS={'commandExecution','fileChange','mcpToolCall','webSearch','imageGeneration','collabAgentToolCall','subAgentActivity','dynamicToolCall'}
RULES=(
    ('deploying',r'\b(?:deploy|rollout|terraform\s+apply|kubectl\s+apply|gh\s+release\s+(?:create|upload))\b'),
    ('testing',r'\b(?:pytest|unittest|vitest|jest|ctest|(?:npm|pnpm|cargo|dotnet|go)\s+(?:run\s+)?test)\b'),
    ('debugging',r'\b(?:debugpy|pdb|gdb|lldb|debugger)\b'),
    ('reviewing',r'\b(?:git\s+diff|gh\s+pr\s+(?:diff|review)|review)\b'),
    ('searching',r'\b(?:rg|grep|ripgrep|glob|search|find|read[ _]file|read[ _]text|get[ -]content)\b'),
    ('editing',r'\b(?:apply[ _]patch|edit[ _]file|write[ _]file|set[ -]content|add[ -]content)\b'),
    ('planning',r'\b(?:update[ _]plan|plan|todo)\b'))
REQUIRED_MODES={'thinking','working','command','waiting','success','failure','listening','afk','sleep','greeting',
                *(mode for mode,pattern in RULES)}


def recent_threads(home):
    """Read only indexed thread IDs to discover already-running chats after a controller restart."""
    databases=[(int(match[1]),path) for path in home.glob('state_*.sqlite')
               if (match:=re.fullmatch(r'state_(\d+)\.sqlite',path.name))]
    if not databases:raise ValueError('No Codex thread metadata database; waiting for a chat to be created.')
    path=max(databases,key=lambda item:item[0])[1]
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.05)) as database:
        return [('local',row[0]) for row in database.execute('SELECT id FROM threads WHERE archived=0 ORDER BY updated_at DESC LIMIT 8')]


def tool_mode(item):
    kind=item.get('type')
    if kind=='fileChange':return 'editing'
    if kind=='webSearch':return 'searching'
    if kind=='commandExecution':
        # Classify executable words only. Quoted text (prompts, script bodies, paths) is never a signal.
        command=re.sub(r'''"(?:`.|[^"`])*"|'(?:''|[^'])*' ''',' ',str(item.get('command',''))+' ',flags=re.X)
        return next((mode for mode,pattern in RULES if re.search(pattern,command,re.I)), 'command')
    name=str(item.get('tool',item.get('name',''))).replace('_',' ').replace('-',' ')
    return next((mode for mode,pattern in RULES if re.search(pattern,name,re.I)), 'working')


def project_item(value):
    result={key:value[key] for key in ITEM_FIELDS if key in value}
    if value.get('type') in TOOLS:result['mode']=tool_mode(value)
    return result


def project_turn(value):
    return {**{key:value[key] for key in TURN_FIELDS if key in value},
        'error':bool(value.get('error')),'items':[project_item(item) for item in value.get('items',[])]}


def project(path,value):
    """Allow only the status tree; even ignored patch values are immediately discarded."""
    if not path:
        return {key:result for key in ('threadRuntimeStatus','requests','turns','turnHistory')
                if key in value and (result:=project([key],value[key])) is not SKIP}
    if path[0]=='requests':return [True]*len(value) if len(path)==1 else True
    if path[0]=='threadRuntimeStatus':
        if len(path)==1:return {key:value[key] for key in ('type','activeFlags') if key in value}
        return value if path[1] in ('type','activeFlags') else SKIP
    if path[0]=='turnHistory':
        if len(path)==1:return {'history':project(['turnHistory','history'],value.get('history',{}))}
        if path[1]!='history':return SKIP
        if len(path)==2:return {'entitiesByKey':project(path+['entitiesByKey'],value.get('entitiesByKey',{}))}
        if path[2]!='entitiesByKey':return SKIP
        if len(path)==3:return {key:project_turn(turn) for key,turn in value.items()}
        tail=path[4:]
    elif path[0]=='turns':
        if len(path)==1:return [project_turn(turn) for turn in value]
        tail=path[2:]
    else:return SKIP
    if not tail:return project_turn(value)
    if tail[0] in TURN_FIELDS:return value if len(tail)==1 else SKIP
    if tail[0]=='error':return bool(value) if len(tail)==1 else SKIP
    if tail[0]!='items':return SKIP
    if len(tail)==1:return [project_item(item) for item in value]
    if len(tail)==2:return project_item(value)
    return value if len(tail)==3 and tail[2] in ITEM_FIELDS else SKIP


class ActivityView:
    def __init__(self):
        self.state,self.revision,self.owner={},None,None
        self.mode,self.reason='idle','no_live_turn'
        self.active=False
        self.terminal_until=0.
        self.turn_id,self.listen_until=None,0.
        self.failed_item,self.failure_until=None,0.

    def accept(self,change,owner,now):
        if change.get('type')=='snapshot':
            self.state=project([],change['conversationState'])
        elif change.get('type')=='patches':
            if self.owner!=owner or self.revision!=change.get('baseRevision'):
                raise ValueError('Activity revision gap; a fresh snapshot is required.')
            for patch in change['patches']:  # IPC carries ordered Immer patches; order and array indices matter.
                path=patch['path']
                if patch['op'] not in ('add','replace','remove'):raise ValueError('Unsupported activity patch operation.')
                value=project(path,patch.get('value')) if patch['op']!='remove' else project(path,{})
                if value is SKIP:continue
                target=self.state
                try:
                    for key in path[:-1]:target=target[key]
                    key=path[-1]
                    if patch['op']=='remove':
                        if isinstance(target,list):target.pop(key)
                        else:target.pop(key,None)
                    elif isinstance(target,list) and patch['op']=='add':target.insert(key,value)
                    else:target[key]=value
                except (KeyError,IndexError,TypeError) as error:
                    raise ValueError('Activity patch structure changed; a fresh snapshot is required.') from error
        else:raise ValueError('Unsupported activity change type.')
        self.owner,self.revision=owner,change['revision']
        self.derive(now)

    def derive(self,now):
        turns=self.state.get('turnHistory',{}).get('history',{}).get('entitiesByKey',{}).values()
        latest=max([*turns,*self.state.get('turns',[])],key=lambda t:t.get('turnStartedAtMs',0),default={})
        runtime=self.state.get('threadRuntimeStatus',{})
        status=latest.get('status')
        was_active=self.active
        self.active=status=='inProgress' or runtime.get('type')=='active'
        self.started=latest.get('turnStartedAtMs',0)
        if self.turn_id!=latest.get('turnId'):
            self.turn_id=latest.get('turnId')
            self.listen_until=now+.6
        if self.state.get('requests') or any('waiting' in str(flag).lower() for flag in runtime.get('activeFlags',[])):
            self.mode,self.reason='waiting','pending_input_or_approval'
        elif status=='failed' or latest.get('error'):
            if was_active:self.terminal_until=now+3
            self.mode,self.reason=('failure','turn_failed') if now<self.terminal_until else ('idle','historical_failure')
        elif self.active:
            items=latest.get('items',[])
            newest=max(items,key=lambda item:item.get('startedAtMs') or 0,default={})
            tools=[item for item in items if item.get('type') in TOOLS and item.get('status') in ('inProgress','pending')]
            tool=max(tools,key=lambda item:item.get('startedAtMs') or 0,default={})
            if newest.get('status')=='failed' and (failure:=(newest.get('id'),newest.get('startedAtMs')))!=self.failed_item:
                self.failed_item,self.failure_until=failure,now+2
            if now<self.failure_until:self.mode,self.reason='failure','tool_failed'
            elif tool and (tool.get('startedAtMs') or 0)>=(newest.get('startedAtMs') or 0):
                self.mode,self.reason=tool['mode'],'active_tool:'+tool['type']
            elif not items and now<self.listen_until:self.mode,self.reason='listening','new_turn_received'
            else:self.mode,self.reason='thinking','active_turn_between_tools'
        elif was_active and status=='completed':
            self.terminal_until=now+2
            self.mode,self.reason='success','turn_completed'
        elif now>=self.terminal_until:self.mode,self.reason='idle','no_live_turn'


class Activity:
    """One own-client subscription per visible/followed thread; no disk state or hook trust edits."""
    def __init__(self):
        self.followers,self.views,self.pending,self.removed={}, {},set(),set()
        self.mode,self.reason='idle','waiting_for_activity_discovery'
        self.candidate,self.since=None,0.
        self.error=None
        self.seeds=set()

    def discover(self,keys):
        keys=set(keys)
        self.removed.update(self.seeds-keys-self.followers.keys())
        self.pending.update(keys-self.views.keys())
        self.seeds=keys
        self.removed.difference_update(keys)

    def receive(self,message,client_id,now=None):
        now=time.monotonic() if now is None else now
        method,params=message.get('method'),message.get('params') or {}
        owner=message.get('sourceClientId')
        if owner==client_id:return
        if method=='thread-stream-following-changed':
            key=(params['hostId'],params['conversationId'])
            followers=self.followers.setdefault(key,set())
            if params['following']:
                followers.add(owner)
                self.removed.discard(key)
                if key not in self.views:self.pending.add(key)
            else:followers.discard(owner)
            if not followers:
                self.followers.pop(key,None)
                self.pending.discard(key)
                if key in self.views and key not in self.seeds:self.removed.add(key)
        elif method=='thread-stream-state-changed':
            key=(params['hostId'],params['conversationId'])
            if key not in self.views:return
            if message.get('version')!=11:raise ValueError('Unsupported activity IPC version; expected 11.')
            try:
                self.views[key].accept(params['change'],owner,now)
                if params['change'].get('type')=='snapshot':self.error=None
            except ValueError as error:
                self.views[key]=ActivityView()
                self.pending.add(key)
                self.reason='resynchronizing_activity_snapshot'
                self.error=str(error)
        elif method=='client-status-changed' and params.get('status')=='disconnected':
            for key,view in list(self.views.items()):  # A disconnected owner must never leave a permanent busy pose.
                if view.owner==params.get('clientId'):
                    self.views.pop(key)
                    if key in self.followers:self.pending.add(key)

    def subscriptions(self):
        pending=list(self.pending)
        self.pending.clear()
        for key in pending:self.views[key]=ActivityView()
        return pending

    def unsubscriptions(self):
        removed=list(self.removed-self.pending)
        self.removed.clear()
        for key in removed:self.views.pop(key,None)
        return removed

    def update(self,now):
        for view in self.views.values():view.derive(now)  # Only content-free projections are retained.
        active=[view for view in self.views.values() if view.active or view.mode=='waiting']
        terminal=[view for view in self.views.values() if now<view.terminal_until]
        view=max(active or terminal,key=lambda view:view.started,default=None)
        candidate=view.mode if view else 'idle'
        if self.candidate!=candidate:self.candidate,self.since=candidate,now
        if candidate in ('waiting','failure') or now-self.since>=.25:
            self.mode=candidate
            self.reason=view.reason if view else 'no_live_turn' if self.views else 'waiting_for_activity_discovery'
        return self.mode
