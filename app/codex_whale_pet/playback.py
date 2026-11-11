"""Validate the optional local animation bank and schedule it on the existing Pet."""
from .activity import REQUIRED_MODES
from .files import contained,digest

SLEEP=('sleep-in','sleep-loop','sleep-out')
BANK_PREFIX='action-bank/'
URGENT={'waiting','failure'}
ONCE={'success','failure','greeting'}


def validate_bank(folder,bank,entries=None):
    if bank is None:
        return
    clips=bank['clips']
    rotation=bank['rotation']
    hover=bank['hover']
    if (bank['schema']!=1 or not clips or not isinstance(hover,list)
            or not set(rotation)<=REQUIRED_MODES|{'idle'} or 'sleep' in rotation
            or any(not isinstance(group,list) or not group or len(set(group))!=len(group) for group in rotation.values())
            or len(set(hover))!=len(hover) or set(hover)&{'hop','waving','eating'}
            or set(clips)!={*SLEEP,*hover,*(key for group in rotation.values() for key in group)}):
        raise ValueError('Invalid local animation registry.')
    paths={clip['path'] for clip in clips.values()}
    if len(paths)!=len(clips):
        raise ValueError('Local animation paths must be unique.')
    for key,clip in clips.items():  # Match every registered image to the package or verify it at controller startup.
        path,hold,sha=clip['path'],clip['hold_ms'],clip['sha256']
        if (not path.startswith(BANK_PREFIX) or not path.endswith('.webp') or type(hold) is not int or not 50<=hold<=15000
                or (clip['loops']!=0 if key=='sleep-loop' else clip['loops']!=1)):
            raise ValueError(f'Invalid local animation: {key}')
        file=contained(folder,path,True)
        if entries is None:
            matches=digest(file)==sha
        else:
            matches=entries.get(path,{}).get('sha256')==sha
        if not matches:
            raise ValueError(f'Local animation checksum mismatch: {key}')


class Playback:
    """Play a finite clip between the original breathing poses; retain each group's rotation cursor."""
    def __init__(self,bank):
        self.clips=bank['clips']
        self.rotation=bank['rotation']
        self.mode,self.current,self.until=None,None,0
        self.cursors={}
        self.sleeping=False

    def update(self,mode,now,suppressed=False,idle_allowed=True):
        if mode in URGENT:
            self.sleeping=False
        elif mode=='sleep':
            if not self.sleeping:
                self.sleeping=True
                self.mode='sleep'
                return self.play(SLEEP[0],now)
            if now>=self.until and self.current!=SLEEP[1]:
                return self.play(SLEEP[1],now)
            return self.current
        elif self.sleeping and mode in {'idle','afk'}:
            self.sleeping=False
            self.mode=mode
            return self.play(SLEEP[2],now)
        elif self.current==SLEEP[2] and now<self.until and mode in {'idle','afk'}:
            return self.current
        elif self.current and self.mode in ONCE and mode=='idle' and now<self.until and not suppressed:
            return self.current  # Finish a terminal reaction if no newer work or interaction takes over.

        self.sleeping=False
        suppressed=suppressed or mode=='idle' and not idle_allowed
        if self.mode!=mode or suppressed or self.current==SLEEP[2]:
            self.mode,self.current=mode,None
            self.until=now+(60 if mode=='idle' else .35 if mode in URGENT|{'success','greeting'} else 1.3)
        group=self.rotation.get(mode)
        if not group or suppressed or now<self.until:
            return self.current
        if self.current:
            self.current=None
            self.until=now+(85 if mode=='idle' else float('inf') if mode in ONCE else 2.8)
            return None
        index=self.cursors.get(mode,0)
        self.cursors[mode]=(index+1)%len(group)
        return self.play(group[index],now)

    def play(self,key,now):
        self.current=key
        self.until=now+self.clips[key]['hold_ms']/1000
        return key
