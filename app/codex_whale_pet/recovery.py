"""An owned, per-user task restarts only this installed controller; Stop stays stopped."""
import datetime
import hashlib
import json
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from .files import OWNER, atomic_json, control_dir

NS='http://schemas.microsoft.com/windows/2004/02/mit/task'
SCRIPT=r'''
$ErrorActionPreference='Stop'
$request=[Console]::In.ReadToEnd() | ConvertFrom-Json
$service=New-Object -ComObject 'Schedule.Service'
$service.Connect()
$folder=$service.GetFolder('\')
$existing=$null
try { $existing=$folder.GetTask($request.name) } catch {
    if ($_.Exception.HResult -ne -2147024894) { throw }
}
if ($null -ne $existing) {
    [xml]$xml=$existing.Xml
    if ($xml.Task.RegistrationInfo.Description -ne $request.owner) { throw 'Recovery task ownership mismatch.' }
}
switch ($request.action) {
    'query' { @{registered=($null -ne $existing)} | ConvertTo-Json -Compress }
    'remove' { if ($null -ne $existing) { $folder.DeleteTask($request.name,0) }; '{}' }
    'run' { if ($null -eq $existing) { throw 'Recovery task is missing.' }; $null=$existing.Run($null); '{}' }
    'enable' {
        $definition=$service.NewTask(0)
        $definition.XmlText=$request.xml
        $sid=[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        $definition.Principal.UserId=$sid
        $definition.Principal.LogonType=3
        $definition.Principal.RunLevel=0
        $definition.Triggers.Item(1).UserId=$sid
        $null=$folder.RegisterTaskDefinition($request.name,$definition,6,$sid,$null,3,$null)
        '{"registered":true}'
    }
    default { throw 'Unknown recovery task action.' }
}
'''


def task_name(root):
    return 'CodexWhaleMusume-'+hashlib.sha256(str(root.resolve()).casefold().encode()).hexdigest()[:12]


def task_xml(record):
    task=ET.Element('Task',{'version':'1.2','xmlns':NS})
    def child(parent,name,value=None):
        node=ET.SubElement(parent,name)
        node.text=value
        return node
    child(child(task,'RegistrationInfo'),'Description',OWNER)
    triggers=child(task,'Triggers')
    child(child(triggers,'LogonTrigger'),'Enabled','true')
    timer=child(triggers,'TimeTrigger')
    child(child(timer,'Repetition'),'Interval','PT1M')
    child(timer,'StartBoundary',(datetime.datetime.now()+datetime.timedelta(minutes=1)).replace(microsecond=0).isoformat())
    child(timer,'Enabled','true')
    principal=child(child(task,'Principals'),'Principal')
    principal.set('id','Author')
    child(principal,'LogonType','InteractiveToken')
    child(principal,'RunLevel','LeastPrivilege')
    settings=child(task,'Settings')
    for name,value in {'MultipleInstancesPolicy':'IgnoreNew','DisallowStartIfOnBatteries':'false',
                       'StopIfGoingOnBatteries':'false','StartWhenAvailable':'true','ExecutionTimeLimit':'PT0S'}.items():
        child(settings,name,value)  # Task Scheduler requires distinct, ordered XML settings.
    action=child(child(task,'Actions'),'Exec')
    child(action,'Command',record['pythonw'])
    child(action,'Arguments',subprocess.list2cmdline([str(Path(record['install_root'])/'app/run.py'),'resume','--install-dir',record['install_root']]))
    return ET.tostring(task,encoding='unicode')


def task(root,action):
    from .manage import state
    record=state(root)
    if os.name!='nt':
        raise OSError('Automatic recovery requires Windows Task Scheduler.')
    payload={'name':task_name(root),'owner':OWNER,'action':action,'xml':task_xml(record) if action=='enable' else None}
    result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',SCRIPT],
        input=json.dumps(payload),capture_output=True,text=True,encoding='utf-8',errors='replace',
        timeout=25,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError('Recovery task operation failed: '+result.stderr.strip())
    return json.loads(result.stdout)


def resume(root):
    from . import manage,windows as win
    record=manage.state(root)
    home=Path(record['codex_home'])
    control=control_dir(home,create=True)
    try:
        if (control/'motion-stop').exists():
            result={'state':'paused','reason':'Stop.cmd requested a persistent pause.'}
        elif win.controller_running():
            result={'state':'already_running',**manage.check_running(root,home)}
        else:
            result=manage.start(root,resuming=True,inline=True)
        atomic_json(control/'recovery-status.json',result)
        return result
    except Exception as error:
        atomic_json(control/'recovery-status.json',{'state':'error','reason':str(error)})
        raise
