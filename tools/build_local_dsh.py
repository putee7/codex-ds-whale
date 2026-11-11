"""Build a local Codex package from verified dsh-pet VP9-alpha clips; no upstream code runs."""
import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

from PIL import Image,ImageDraw
from atlas_encoding import clear_transparent_rgb,exact_webp_image_chunks,webp_chunk
from build_modes import COUNTS

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
from codex_whale_pet.files import atomic_bytes,atomic_json,contained,digest,read_json,verify_assets

LOCK=read_json(ROOT/'tools/dsh-source-lock.json')
UPSTREAM=f"https://github.com/{LOCK['upstream']}"
RAW=f"https://raw.githubusercontent.com/{LOCK['upstream']}/{LOCK['commit']}/"
SLEEP=('sleep-in','sleep-loop','sleep-out')
ROTATION={
    'idle':['yawn','stretch'], 'thinking':['think','deep-think'], 'working':['busy','note'],
    'command':['busy','code'], 'editing':['code','note'], 'searching':['note','think'],
    'testing':['busy','organize'], 'reviewing':['organize','note'], 'planning':['note','organize'],
    'deploying':['organize','busy'], 'debugging':['deep-think','code'], 'waiting':['wait'],
    'success':['celebrate'], 'failure':['sigh'], 'greeting':['greet'],
}
HOVER=['shy','tickle','snack','rice','hotpot']
RUNTIME_MS={'sleep-in':4000,'sleep-out':3000,'sleep-loop':10000,'greet':3500,'sigh':3500,'hop':2800,'wave':2800,
            'celebrate':4500,**dict.fromkeys(HOVER,5250)}
FPS=8
TILE=(192,208)
CANVAS=(1536,2288)
DRAG=(0,208,1536,624)
LIMIT=20*1024*1024
ALPHA=[0,0,0,0,*range(4,256)]  # VP9-alpha encoding leaves near-transparent speckle across the source canvas.


def verify_clip(data,key,entry):
    if (hashlib.sha256(data).hexdigest()!=entry['sha256']
            or hashlib.sha1(f'blob {len(data)}\0'.encode()+data).hexdigest()!=entry['git_blob_sha1']):
        raise ValueError(f'Unexpected source bytes for {key}.')


def fetch_sources(root,entries):
    def fetch(pair):
        key,entry=pair
        file=contained(root,entry['file'])
        if file.is_file():
            verify_clip(file.read_bytes(),key,entry)
            return
        with urlopen(RAW+quote(entry['file']),timeout=35) as response:
            data=response.read()
        verify_clip(data,key,entry)
        file.parent.mkdir(parents=True,exist_ok=True)
        atomic_bytes(file,data)
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(fetch,entries.items()))


def load_clip(root,key,entry):
    source=contained(root,entry['file'],True)
    verify_clip(source.read_bytes(),key,entry)
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries',
                'stream=width,height:format=duration','-of','json',str(source)]))
    stream=probe['streams'][0]
    width,height=stream['width'],stream['height']
    seconds=RUNTIME_MS.get(key,6500)/1000
    ratio=seconds/float(probe['format']['duration'])
    raw=subprocess.check_output(['ffmpeg','-v','error','-threads','2','-c:v','libvpx-vp9','-i',str(source),
        '-an','-vf',f'setpts={ratio:.9f}*PTS,fps={FPS},format=rgba','-threads','1',
        '-f','rawvideo','-pix_fmt','rgba','-'],stderr=subprocess.PIPE)
    frame_bytes=width*height*4
    if len(raw)%frame_bytes or len(raw)//frame_bytes<8:
        raise ValueError(f'Invalid raw frames for {key}.')
    poses=[]
    for start in range(0,len(raw),frame_bytes):  # Source alpha bounds are needed to fit the entire sequence, including props.
        frame=Image.frombytes('RGBA',(width,height),raw[start:start+frame_bytes])
        frame.putalpha(frame.getchannel('A').point(ALPHA))
        alpha=frame.getchannel('A')
        box=(alpha.point([0]*16+[255]*240) if key in SLEEP else alpha).getbbox()
        if box is None or box==(0,0,width,height):
            raise ValueError(f'Empty frame or alpha plane lost in {key}.')
        poses.append((box,frame.crop(box)))
    return poses


def fit(poses,anchor):
    left,top,right,bottom=zip(*(box for box,_ in poses))
    left,top,right,bottom=min(left),min(top),max(right),max(bottom)
    center=(anchor[0]+anchor[2])/2
    feet=anchor[3]
    # Use one transform per sequence (one across all sleep phases); cropping each frame independently causes jitter.
    scale=min(90/max(center-left,right-center),196/(bottom-top),191/(feet-anchor[1]))
    baseline=min(202,205-(bottom-feet)*scale)
    result=[]
    for box,frame in poses:
        x0,y0,x1,y1=box
        x0,x1=round(96+(x0-center)*scale),round(96+(x1-center)*scale)
        y0,y1=round(baseline+(y0-feet)*scale),round(baseline+(y1-feet)*scale)
        tile=Image.new('RGBA',TILE)
        tile.paste(frame.resize((max(1,x1-x0),max(1,y1-y0)),Image.Resampling.LANCZOS),(x0,y0))
        box=tile.getchannel('A').getbbox()
        if not box or box[0]<3 or box[1]<3 or box[2]>189 or box[3]>207:
            raise ValueError('Local animation touches a cell edge.')
        result.append(clear_transparent_rgb(tile))
    return result


def encode(master,poses,output,loops,durations=None):
    uint24=lambda n:n.to_bytes(3,'little')
    parts=[webp_chunk(b'VP8X',bytes((0x12,0,0,0))+uint24(1535)+uint24(2287)),
           webp_chunk(b'ANIM',b'\0'*4+loops.to_bytes(2,'little'))]
    expected=[]
    frame=master.copy()
    composite=master.copy()
    durations=[1000//FPS]*len(poses) if durations is None else durations
    if len(durations)!=len(poses) or any(type(ms) is not int or ms<50 for ms in durations):
        raise ValueError('Each pose needs a duration of at least 50 ms.')
    for index,(pose,interval) in enumerate(zip(poses,durations)):  # Exact strips retain the native drag rows.
        for row,count in COUNTS.items():
            frame.paste((0,0,0,0),(0,row*208,1536,(row+1)*208))
            for column in range(count):
                frame.paste(pose,(column*192,row*208))
        rectangles=[((0,0,*CANVAS),interval)] if index==0 else [((0,0,1536,208),25),((0,624,*CANVAS),interval-25)]
        for rect,ms in rectangles:
            x,y,right,bottom=rect
            patch=frame.crop(rect)
            header=uint24(x//2)+uint24(y//2)+uint24(right-x-1)+uint24(bottom-y-1)+uint24(ms)+b'\x02'
            parts.append(webp_chunk(b'ANMF',header+exact_webp_image_chunks(patch,method=0)))
            composite.paste(patch,(x,y))
            expected.append(hashlib.sha256(composite.tobytes()).digest())
    payload=b'WEBP'+b''.join(parts)
    if len(payload)+8>LIMIT:
        raise ValueError(f'{output.name} exceeds the native 20 MiB limit.')
    output.write_bytes(b'RIFF'+struct.pack('<I',len(payload))+payload)
    with Image.open(output) as decoded:
        if decoded.n_frames!=len(expected) or decoded.info['loop']!=loops:
            raise ValueError(f'{output.name}: incomplete animation.')
        for index,sha in enumerate(expected):
            decoded.seek(index)
            if hashlib.sha256(decoded.convert('RGBA').tobytes()).digest()!=sha:
                raise ValueError(f'{output.name}: pixel mismatch in frame {index}.')
    return {'sha256':digest(output),'hold_ms':sum(durations),'loops':loops,'pose_frames':len(poses)}


def build(source,output,appearance=None,fetch=False):
    source,output=source.resolve(),output.resolve()
    if not output.is_relative_to((ROOT/'build').resolve()) or output.exists() or source.is_relative_to(output):
        raise ValueError('Choose a new destination below the project build directory.')
    entries=LOCK['animation']
    if entries.keys()!={*SLEEP,*HOVER,*(item for group in ROTATION.values() for item in group)}:
        raise ValueError('The locked animation set is incomplete.')
    if fetch:
        fetch_sources(source,{**entries,**(LOCK['appearance'] if appearance else {})})
    manifest=json.loads((ROOT/'assets-manifest.json').read_text(encoding='utf-8-sig'))
    verify_assets(ROOT/'pet',manifest)
    output.mkdir(parents=True)
    for name in ('app','runtime'):
        shutil.copytree(ROOT/name,output/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    (output/'scripts').mkdir()
    shutil.copyfile(ROOT/'scripts/bootstrap.ps1',output/'scripts/bootstrap.ps1')
    for name in ('Install.cmd','runtime.json','runtime-files.json','LICENSE','THIRD_PARTY_NOTICES.md'):
        shutil.copyfile(ROOT/name,output/name)
    shutil.copyfile(ROOT/'docs/dsh-package.md',output/'README.md')
    pet=output/'pet'
    if appearance:
        from dsh_appearance import build_appearance
        manifest=build_appearance(source,entries,appearance.resolve(),pet)
    else:
        shutil.copytree(ROOT/'pet',pet)
    bank=pet/'action-bank'
    bank.mkdir()
    master=Image.open(pet/'spritesheet.webp').convert('RGBA')
    drag=master.crop(DRAG).tobytes()
    sleep=[load_clip(source,key,entries[key]) for key in SLEEP]
    sizes=list(map(len,sleep))
    fitted=fit(sum(sleep,[]),sleep[0][0][0])
    shared=dict(zip(SLEEP,(fitted[:sizes[0]],fitted[sizes[0]:sum(sizes[:2])],fitted[-sizes[2]:])))
    del sleep,fitted

    def convert(key):
        poses=shared.get(key)
        if poses is None:
            decoded=load_clip(source,key,entries[key])
            poses=fit(decoded,decoded[0][0])
        file=bank/f'{key}.webp'
        report=encode(master,poses,file,0 if key=='sleep-loop' else 1)
        with Image.open(file) as check:
            if check.convert('RGBA').crop(DRAG).tobytes()!=drag:
                raise ValueError(f'{key}: native drag pose changed.')
        return key,{'path':file.relative_to(pet).as_posix(),**report},(poses[0],poses[len(poses)//3],poses[-1])

    with ThreadPoolExecutor(max_workers=3) as pool:
        converted=list(pool.map(convert,entries))
    clips={key:report for key,report,_ in converted}
    metadata_path=pet/'motion-assets.json'
    metadata=json.loads(metadata_path.read_text(encoding='utf-8-sig'))
    metadata['animation_bank']={'schema':1,'clips':clips,'rotation':ROTATION,'hover':HOVER}
    atomic_json(metadata_path,metadata)
    provenance=bank/'PROVENANCE.json'
    atomic_json(provenance,{'upstream':UPSTREAM,'commit':LOCK['commit'],'source':entries,'artwork_license':'CC BY-NC-SA 4.0',
        'license_url':'https://creativecommons.org/licenses/by-nc-sa/4.0/','credits':['PC2005-cloud','ZipZipPipe','上善无形'],
        'changes':'Retimed and resized the transparent WebM clips, then composed Codex v2 animated WebP atlases. Local noncommercial use.'})
    for file in (metadata_path,provenance,*bank.glob('*.webp')):
        manifest['files'][file.relative_to(pet).as_posix()]={'bytes':file.stat().st_size,'sha256':digest(file)}
    atomic_json(output/'assets-manifest.json',manifest)
    verify_assets(pet,manifest)
    sheet=Image.new('RGB',(12*128,((len(converted)+3)//4)*156),(237,242,248))
    draw=ImageDraw.Draw(sheet)
    for i,(key,_,poses) in enumerate(converted):
        x,y=i%4*384,i//4*156
        for j,pose in enumerate(poses):
            tile=pose.copy()
            tile.thumbnail((125,132))
            sheet.paste(tile,(x+j*128,y),tile)
        draw.text((x+6,y+135),key,fill='#252e45')
    sheet.save(output/'preview.png')
    print(json.dumps({'clips':len(clips),'bytes':sum(p.stat().st_size for p in bank.glob('*.webp')),
        'poses':sum(clip['pose_frames'] for clip in clips.values()),'largest':max(p.stat().st_size for p in bank.glob('*.webp'))}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--appearance',type=Path,help='Use the locally validated DSH chibi pose inputs.')
    parser.add_argument('--fetch',action='store_true',help='Fetch missing clips at the pinned upstream commit.')
    options=parser.parse_args()
    build(options.source,options.output,options.appearance,options.fetch)
