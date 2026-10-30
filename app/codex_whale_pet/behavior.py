"""Deterministic input behavior; no operating-system or network access."""
import math
import random
import struct

RANGE_DIP=500
RANGE_EXIT_DIP=550
IDLE_SECONDS=4

def direction(point, center, previous=None, scale=1):
    dx, dy = point[0]-center[0], point[1]-center[1]
    if math.hypot(dx, dy) < 18*scale:
        return previous
    angle = math.degrees(math.atan2(dx, -dy)) % 360
    nearest = int((angle+11.25)//22.5) % 16
    if previous is not None:
        distance = abs((angle-previous*22.5+180) % 360-180)
        if distance < 14.25:  # Three-degree hysteresis limits jitter without making turns sticky.
            return previous
    return nearest

class FollowState:
    def __init__(self):
        self.last_point, self.last_motion, self.previous = None, None, None
        self.engaged, self.reason = False, 'outside_range'

    def update(self, point, center, scale, now):
        if self.last_point is None or math.dist(point, self.last_point) >= 2*scale:
            self.last_point, self.last_motion = point, now
        distance = math.dist(point, center)/scale
        self.engaged = distance <= (RANGE_EXIT_DIP if self.engaged else RANGE_DIP)
        if not self.engaged or now-self.last_motion >= IDLE_SECONDS:
            self.previous = None
            self.reason = 'idle_timeout' if self.engaged else 'outside_range'
            self.engaged = False
        else:
            self.previous = direction(point, center, self.previous, scale)
            self.reason = 'tracking' if self.previous is not None else 'center_deadzone'
        return self.previous

def on_body(point, layout, margin=0):
    width=layout['width_dip']
    height=math.ceil(width*208/192)
    return (abs(point[0]-layout['center'][0])/layout['scale']<=width/2+margin and
            abs(point[1]-layout['center'][1])/layout['scale']<=height/2+margin)

class HoverState:
    """Shuffle all registered actions once per round, never repeat across round boundaries."""
    def __init__(self, actions, rng=None):
        assert len(actions)>=2,'Hover requires at least two registered actions.'
        self.actions,self.rng=actions,rng or random.Random()
        self.bag,self.last=[],None
        self.current,self.inside,self.next_at,self.until=None,False,0.,0.

    def update(self, inside, now):
        if not inside:
            self.inside,self.current=False,None
            return None
        if not self.inside:
            self.inside,self.next_at=True,now+.06
        if self.current is not None:
            if now<self.until:
                return self.current
            self.current,self.next_at=None,now+.7
            return None
        if now<self.next_at:
            return None
        if not self.bag:
            self.bag=list(self.actions)
            self.rng.shuffle(self.bag)
            if self.bag[-1]==self.last:
                self.bag[0],self.bag[-1]=self.bag[-1],self.bag[0]
        self.current=self.last=self.bag.pop()
        self.until=now+self.actions[self.current]['hold_ms']/1000
        return self.current

def replay_webp(template, nonce):
    assert template[:4]==b'RIFF' and template[8:12]==b'WEBP'
    stamp=nonce.encode('ascii')
    chunk=b'whal'+struct.pack('<I',len(stamp))+stamp+(b'\0' if len(stamp)%2 else b'')
    payload=template[8:]+chunk
    return b'RIFF'+struct.pack('<I',len(payload))+payload
