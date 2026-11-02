"""Human maintenance commands; never print authentication/configuration contents."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from . import __version__,manage


def main():
    parser=argparse.ArgumentParser(description='Codex Whale Musume native Pet / 官方鲸鱼娘')
    parser.add_argument('--version',action='version',version=__version__)
    commands=parser.add_subparsers(dest='command',required=True)
    for name in ('install','start','stop','doctor','uninstall','run','resume','repair','enable-recovery','disable-recovery'):
        command=commands.add_parser(name)
        command.add_argument('--install-dir',type=Path,help='Dedicated application directory; default LOCALAPPDATA/CodexWhaleMusume')
        command.add_argument('--home',type=Path,help='Codex home; default CODEX_HOME or the user .codex directory')
        if name in ('install','start','run'):
            command.add_argument('--allow-untested',action='store_true',help='Legacy compatibility flag; version numbers no longer bypass or replace interface checks')
        if name=='install':
            command.add_argument('--package-root',type=Path,default=Path(__file__).resolve().parents[2])
            command.add_argument('--no-start',action='store_true')
            command.add_argument('--use-current-python',action='store_true',help='Explicit source-development mode when no embedded runtime is present')
    args=parser.parse_args()
    try:
        if args.command=='run':
            from .controller import run
            run((args.home or manage.default_home()).resolve(),args.allow_untested)
            return 0
        home=(args.home or manage.default_home()).resolve()
        root=(args.install_dir or manage.default_install(home)).resolve()
        if args.command not in ('install','uninstall') and Path(__file__).resolve().parents[2]!=root:
            record=manage.state(root)
            return subprocess.run([record['python'],str(root/'app/run.py'),*sys.argv[1:],'--install-dir',str(root)]).returncode
        if args.command=='install':
            home=(args.home or manage.default_home()).resolve()
            record=manage.install(args.package_root,home,root,args.use_current_python)
            result={'installed':True,'version':record['version'],'pet_id':'whale-musume',
                    'next':'Codex Settings > Mini and pets > Refresh > Whale Musume > Show Mini'}
            if not args.no_start:
                from . import selection,windows as win
                result['local_mode']=selection.request(home,win.selected_pet(home))
                from .recovery import task
                result['recovery']=task(root,'enable')
                result['controller']=manage.start(root,args.allow_untested)
        elif args.command=='start':
            result=manage.start(root,args.allow_untested)
        elif args.command=='stop':
            home=(args.home or Path(manage.state(root)['codex_home'])).resolve()
            manage.stop(home)
            result={'stopped':True,'native_pet_retained':True}
        elif args.command=='doctor':
            result=manage.doctor(root)
        elif args.command=='resume':
            from .recovery import resume
            result=resume(root)
        elif args.command=='repair':
            from . import selection,windows as win
            home=Path(manage.state(root)['codex_home'])
            result=selection.request(home,win.selected_pet(home))
            applied=selection.maintain(home,lambda:not win.codex_processes())
            result={'local_mode':applied or result,'controller':manage.start(root)}
        elif args.command in ('enable-recovery','disable-recovery'):
            from .recovery import task
            result=task(root,'enable' if args.command=='enable-recovery' else 'remove')
        else:
            result=manage.uninstall(root)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except Exception as error:
        print(f'ERROR: {error}',file=sys.stderr)
        return 1
