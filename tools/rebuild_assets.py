"""Rebuild approved pixels into native animation assets. Never reads or writes a user Codex home."""
import argparse
import hashlib
import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image
from atlas_encoding import clear_transparent_rgb,encode_fast_gaze_breath,encode_hover_action,encode_look_breath

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'build/pet')
    args=parser.parse_args()
    out=args.output.resolve()
    if out.exists():
        raise SystemExit('Output already exists; choose a new build directory.')
    out.mkdir(parents=True)
    master=ROOT/'pet/spritesheet.webp'
    base=Image.open(master).convert('RGBA')
    shutil.copy2(master,out/'spritesheet.webp')
    encode_look_breath(master,out/'spritesheet-look-breath.png')
    gaze=out/'.gaze'
    gaze.mkdir()

    def build_direction(index):
        frame=base.copy()
        pose=base.crop((index%8*192,(9+index//8)*208,(index%8+1)*192,(10+index//8)*208))
        feet=pose.getchannel('A').crop((55,190,120,208)).getbbox()
        dx=round(86-(55+(feet[0]+feet[2])/2))
        dy=203-(190+feet[3])
        moved=clear_transparent_rgb(pose.convert('RGBa').transform((192,208),Image.Transform.AFFINE,
            (1,0,-dx,0,1,-dy),resample=Image.Resampling.BICUBIC).convert('RGBA'))
        for column in range(6):  # The native six timed columns all share the container's current phase.
            frame.paste(moved,(column*192,0))
        temporary=gaze/f'{index:02}.png'
        frame.save(temporary)
        report=encode_fast_gaze_breath(temporary,gaze/f'{index:02}.webp')
        temporary.unlink()
        return report

    with ThreadPoolExecutor(max_workers=2) as workers:
        directions=list(workers.map(build_direction,range(16)))
    revision=hashlib.sha256(''.join(item['sha256'] for item in directions).encode()).hexdigest()[:12]
    master_sha=hashlib.sha256(master.read_bytes()).hexdigest()
    gaze_name=f'gaze-bank/{master_sha[:16]}-{revision}'
    (out/'gaze-bank').mkdir()
    os.replace(gaze,out/gaze_name)
    canonical=base.crop((0,0,192,208))
    eating=[Image.open(ROOT/'artwork/eating'/f'{index:02}.png').convert('RGBA') for index in range(8)]
    eating[0]=canonical.copy();eating[-1]=canonical.copy()
    actions={
        'hop':([base.crop((i*192,832,(i+1)*192,1040)) for i in range(5)],[140,140,140,140,280],3,2800),
        'waving':([base.crop((i*192,624,(i+1)*192,832)) for i in range(4)]+[canonical],[140,140,140,280,350],2,2800),
        'eating':(eating,[160,360,360,500,460,460,400,900],1,3600)}
    hover=out/'.hover'
    hover.mkdir()
    reports={}
    for name,(poses,durations,loops,hold) in actions.items():
        reports[name]=encode_hover_action(master,poses,durations,hover/f'{name}.webp',loops)
        reports[name]['hold_ms']=hold
    revision=hashlib.sha256(''.join(item['sha256'] for item in reports.values()).encode()).hexdigest()[:12]
    hover_name=f'hover-bank/{revision}'
    (out/'hover-bank').mkdir()
    os.replace(hover,out/hover_name)
    metadata={'source_sha256':master_sha,'app_version':'26.1023.6621.0','bank':gaze_name,'direction_extension':'webp',
        'hover_source_sha256':master_sha,'hover_live_path':hover_name+'/active.webp',
        'hover_actions':{name:{'path':hover_name+'/'+report['file'],'sha256':report['sha256'],'hold_ms':report['hold_ms']} for name,report in reports.items()}}
    (out/'motion-assets.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8',newline='\n')
    for name in ('pet.json','LICENSE'):
        shutil.copy2(ROOT/'pet'/name,out/name)
    manifest={'schema':1,'pet_id':'whale-musume','pet_manifest':json.loads((out/'pet.json').read_text(encoding='utf-8')),
        'files':{file.relative_to(out).as_posix():{'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'bytes':file.stat().st_size}
                 for file in sorted(out.rglob('*')) if file.is_file()}}
    (out.parent/'assets-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'ok':True,'files':len(manifest['files']),'output':str(out),'source_art_regenerated':False}))


if __name__=='__main__':main()
