"""Build pinned DSH poses with gentle breathing for every non-drag native state."""
import argparse
import hashlib
import json
import struct
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PIL import Image
from atlas_encoding import OFFSETS,DURATIONS,clear_transparent_rgb,exact_webp_image_chunks,webp_chunk

ROOT=Path(__file__).resolve().parents[1]
COUNTS={0:6,3:4,4:5,5:8,6:6,7:6,8:6,9:8,10:8}


def fit_pose(source):
    image=Image.open(source).convert('RGBA')
    box=image.getchannel('A').getbbox()
    if box is None:raise ValueError('Mode pose is empty.')
    image=image.crop(box)
    image.thumbnail((180,194),Image.Resampling.LANCZOS)
    pose=Image.new('RGBA',(192,208))
    pose.alpha_composite(image,((192-image.width)//2,203-image.height))
    return clear_transparent_rgb(pose)


def encode_mode(master,pose,output):
    uint24=lambda value:int(value).to_bytes(3,'little')
    parts=[webp_chunk(b'VP8X',bytes((0x12,0,0,0))+uint24(1535)+uint24(2287)),webp_chunk(b'ANIM',b'\0'*6)]
    composite=master.copy()
    expected=[]
    for phase,(offset,duration) in enumerate(zip(OFFSETS,DURATIONS)):  # Container phases preserve breathing across native timer columns.
        moved=clear_transparent_rgb(pose.convert('RGBa').transform((192,208),Image.Transform.AFFINE,
            (1,0,0,0,1,-offset),resample=Image.Resampling.BICUBIC).convert('RGBA'))
        frame=master.copy()
        for row,count in COUNTS.items():
            frame.paste((0,0,0,0),(0,row*208,1536,(row+1)*208))
            for column in range(count):frame.paste(moved,(column*192,row*208))
        rectangles=[((0,0,1536,2288),duration)] if phase==0 else [((0,0,1536,208),25),((0,624,1536,2288),duration-25)]
        for (left,top,right,bottom),pause in rectangles:
            cropped=frame.crop((left,top,right,bottom))
            header=uint24(left//2)+uint24(top//2)+uint24(right-left-1)+uint24(bottom-top-1)+uint24(pause)+b'\x02'
            parts.append(webp_chunk(b'ANMF',header+exact_webp_image_chunks(cropped)))
            composite.paste(cropped,(left,top))
            expected.append(hashlib.sha256(composite.tobytes()).digest())
    payload=b'WEBP'+b''.join(parts)
    output.write_bytes(b'RIFF'+struct.pack('<I',len(payload))+payload)
    if output.stat().st_size>20*1024*1024:raise ValueError('Native mode atlas exceeds 20 MiB.')
    with Image.open(output) as check:
        if check.n_frames!=7:raise ValueError('Breathing phases were lost.')
        for index,sha in enumerate(expected):
            check.seek(index)
            if hashlib.sha256(check.convert('RGBA').tobytes()).digest()!=sha:raise ValueError('Mode encoding changed pixels.')
            if check.convert('RGBA').crop((0,208,1536,624)).tobytes()!=master.crop((0,208,1536,624)).tobytes():
                raise ValueError('Native drag animations changed.')
    return {'path':output.name,'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'cycle_ms':sum(DURATIONS)}


def build_modes(output):
    if output.exists():raise ValueError('Choose a new mode build directory.')
    output.mkdir(parents=True)
    registry=json.loads((ROOT/'artwork/modes/registry.json').read_text(encoding='utf-8'))
    master=Image.open(ROOT/'pet/spritesheet.webp').convert('RGBA')
    poses=list(dict.fromkeys(item['pose'] for item in registry['modes'].values()))
    def build(name):return name,encode_mode(master,fit_pose(ROOT/'artwork/modes'/f'{name}.webp'),output/f'{name}.webp')
    with ThreadPoolExecutor(max_workers=2) as workers:reports=dict(workers.map(build,poses))
    revision=hashlib.sha256(''.join(report['sha256'] for report in reports.values()).encode()).hexdigest()[:12]
    result={name:{**reports[item['pose']],'label':item['label'],'pose':item['pose']} for name,item in registry['modes'].items()}
    registry={'revision':revision,'modes':result}
    (output/'registry.json').write_text(json.dumps(registry,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    return registry


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'build/modes')
    args=parser.parse_args()
    result=build_modes(args.output)
    print(json.dumps({'ok':True,'modes':len(result['modes']),'revision':result['revision'],
        'bytes':sum(p.stat().st_size for p in args.output.glob('*.webp'))}))


if __name__=='__main__':main()
