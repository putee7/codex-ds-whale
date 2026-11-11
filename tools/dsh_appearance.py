"""Compose the DSH chibi skin from pinned source frames and locally approved supplemental poses."""
import shutil
from concurrent.futures import ThreadPoolExecutor

from PIL import Image,ImageDraw
from atlas_encoding import encode_fast_gaze_breath,encode_look_breath
from build_local_dsh import CANVAS,LOCK,ROOT,TILE,UPSTREAM,encode,fit,load_clip
from build_modes import COUNTS,encode_mode
from codex_whale_pet.files import atomic_json,digest,read_json

EXTRAS={'base','look','drag','hop','wave','alert'}
MODE_FRAME={
    'thinking':('think',16),'working':('busy',18),'command':('code',12),'editing':('note',24),
    'searching':('note',6),'testing':('code',44),'reviewing':('organize',17),'deploying':('organize',7),
    'debugging':('alert',25),'planning':('note',14),'waiting':('wait',33),'success':('celebrate',15),
    'failure':('sigh',19),'listening':('look',35),'afk':('yawn',29),'sleep':('sleep-loop',26),'greeting':('greet',11),
}


def local_tile(folder,name,files):
    file=folder/f'{name}.png'
    if digest(file)!=files[file.name]:
        raise ValueError(f'Q-style pose checksum mismatch: {name}.')
    with Image.open(file) as image:
        tile=image.convert('RGBA')
    box=tile.getchannel('A').getbbox()
    if tile.size!=TILE or not box or min(box[0],box[1],192-box[2],208-box[3])<3:
        raise ValueError(f'{name} must be a complete transparent 192 × 208 pose with margins.')
    return tile


def evenly(poses,count,start=0,end=None):
    end=len(poses)-1 if end is None else end
    return [poses[round(start+i*(end-start)/(count-1))] for i in range(count)]


def write_preview(output,canonical,gaze,actions,mode_poses):
    rows=[
        ('DSH idle + work poses',[canonical,mode_poses['thinking'],mode_poses['command'],mode_poses['waiting'],
            mode_poses['success'],mode_poses['sleep']]),
        ('Gaze N to SSE',gaze[:8]),('Gaze S to NNW',gaze[8:]),
        ('Hover: hop / wave / steel basin rice',[actions['hop'][len(actions['hop'])//2],
            actions['waving'][len(actions['waving'])//2],*actions['eating'][1:4],actions['eating'][6]]),
    ]
    sheet=Image.new('RGB',(8*152,len(rows)*184),(239,244,250))
    draw=ImageDraw.Draw(sheet)
    for j,(name,poses) in enumerate(rows):
        y=j*184
        draw.text((12,y+8),name,fill='#22304b')
        for i,pose in enumerate(poses):
            tile=pose.copy()
            tile.thumbnail((147,152))
            sheet.paste(tile,(i*152+(152-tile.width)//2,y+25),tile)
    sheet.save(output)


def build_appearance(source,entries,art,pet):
    extra=LOCK['appearance']
    if extra.keys()!=EXTRAS:
        raise ValueError('The locked appearance set is incomplete.')
    all_sources={**entries,**extra}
    keys={*extra,*(name for name,_ in MODE_FRAME.values())}
    def fitted(key):
        source_poses=load_clip(source,key,all_sources[key])
        return key,fit(source_poses,source_poses[0][0])
    with ThreadPoolExecutor(max_workers=3) as pool:
        poses=dict(pool.map(fitted,sorted(keys)))
    canonical=poses['base'][0]
    custom=read_json(art/'poses.json')
    gaze=[local_tile(art,f'gaze-{i:02}',custom['gaze']['files']) for i in range(16)]
    if len({tile.tobytes() for tile in gaze})!=16:
        raise ValueError('Each gaze slot must have its own pose.')
    rice=[local_tile(art,f'rice-{i:02}',custom['rice']['files']) for i in range(4)]
    action={'hop':poses['hop'],'waving':poses['wave'],
            'eating':[canonical,rice[0],rice[1],rice[2],rice[1],rice[2],rice[3],canonical]}
    mode_poses={name:poses[key][index] for name,(key,index) in MODE_FRAME.items()}
    cells={0:[canonical]*6,1:evenly(poses['drag'],8,6,44),2:evenly(poses['drag'],8,8,46),
           3:evenly(poses['wave'],4,5,len(poses['wave'])-4),4:evenly(poses['hop'],5,4,len(poses['hop'])-4),
           5:evenly(poses['sigh'],8,4,24),6:evenly(poses['wait'],6,18,44),7:evenly(poses['code'],6,6,44),
           8:evenly(poses['organize'],6,8,39),9:gaze[:8],10:gaze[8:]}
    if {row:len(tiles) for row,tiles in cells.items()}!={**COUNTS,1:8,2:8}:
        raise ValueError('Native atlas slot counts changed.')
    master=Image.new('RGBA',CANVAS)
    for row,tiles in cells.items():  # Sprite order is part of Codex's native v2 contract.
        for col,tile in enumerate(tiles):
            master.paste(tile,(192*col,208*row))
    pet.mkdir()
    master_path=pet/'spritesheet.webp'
    master.save(master_path,format='WEBP',lossless=True,exact=True,method=4)
    with Image.open(master_path) as check:
        if check.convert('RGBA').tobytes()!=master.tobytes():
            raise ValueError('The master changed while encoding.')
    sha=digest(master_path)
    paths={name:f'{name}-bank/{sha[:12]}' for name in ('gaze','hover','mode')}
    for path in paths.values():
        (pet/path).mkdir(parents=True)
    encode_look_breath(master_path,pet/'spritesheet-look-breath.png',idle_breath=True)

    def direction(i):
        frame=master.copy()
        for col in range(6):
            frame.paste(gaze[i],(192*col,0))
        return encode_fast_gaze_breath(frame,pet/paths['gaze']/f'{i:02}.webp',method=0)

    def mode(name):
        path=f"{paths['mode']}/{name}.webp"
        report=encode_mode(master,mode_poses[name],pet/path,method=0)
        return name,{**report,'path':path,'label':labels[name]['label'],'pose':name}

    labels=read_json(ROOT/'artwork/modes/registry.json')['modes']
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(direction,range(16)))
        modes=dict(pool.map(mode,MODE_FRAME))
    hover={}
    for name,frames in action.items():
        path=f"{paths['hover']}/{name}.webp"
        durations=[160,410,360,540,380,520,430,800] if name=='eating' else None
        report=encode(master,frames,pet/path,loops=1,durations=durations)
        hover[name]={'path':path,'sha256':report['sha256'],'hold_ms':report['hold_ms']}
    metadata={'source_sha256':sha,'app_version':'26.1103.7773.0','bank':paths['gaze'],'direction_extension':'webp',
        'hover_source_sha256':sha,'hover_live_path':paths['hover']+'/active.webp',
        'hover_actions':hover,'activity_modes':modes}
    atomic_json(pet/'motion-assets.json',metadata)
    profile=read_json(ROOT/'pet/pet.json')
    profile['description']='DSH Q 版鲸鱼娘：鼠标注视、轻呼吸、工作动作与铁盆吃饭。素材来自 PC2005-cloud/dsh-pet。'
    atomic_json(pet/'pet.json',profile)
    shutil.copyfile(ROOT/'artwork/dsh-chibi/LICENSE.md',pet/'APPEARANCE-LICENSE.md')
    atomic_json(pet/'APPEARANCE.json',{'upstream':UPSTREAM,'commit':LOCK['commit'],
        'license':'CC BY-NC-SA 4.0','license_url':'https://creativecommons.org/licenses/by-nc-sa/4.0/',
        'credits':['PC2005-cloud','ZipZipPipe','上善无形'],'source':{key:all_sources[key] for key in sorted(keys)},
        'custom':custom})
    write_preview(pet.parent/'appearance-preview.png',canonical,gaze,action,mode_poses)
    return {'schema':1,'pet_id':'whale-musume','pet_manifest':profile,'files':{
        file.relative_to(pet).as_posix():{'bytes':file.stat().st_size,'sha256':digest(file)}
        for file in sorted(pet.rglob('*')) if file.is_file()}}
