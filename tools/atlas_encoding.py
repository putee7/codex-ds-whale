"""Encode approved gaze poses with tiny temporal offsets; never redraw the character."""
import hashlib
import io
import json
import struct
from pathlib import Path

from PIL import Image

OFFSETS=(0.0,-0.5,-1.0,-0.5)
DURATIONS=(300,800,1200,900)


def clear_transparent_rgb(image):
    # Fractional resampling can round alpha to zero while leaving RGB residue; the Pet contract forbids it.
    image.paste((0,0,0,0), (0,0,image.width,image.height),
                image.getchannel('A').point([255]+[0]*255))
    return image


def encode_look_breath(source,output):
    base=Image.open(source).convert('RGBA')
    assert base.size==(1536,2288),'A v2 atlas is required.'
    frames=[]
    # The sixteen existing poses are distinct data cells and must be translated within their own slots.
    for offset in OFFSETS:
        frame=base.copy()
        if offset:
            for row in (9,10):
                for column in range(8):
                    box=(column*192,row*208,(column+1)*192,(row+1)*208)
                    pose=base.crop(box)
                    assert pose.getchannel('A').getbbox()[1]>1,'Insufficient headroom for one-pixel float.'
                    if offset.is_integer():
                        moved=Image.new('RGBA',(192,208))
                        moved.alpha_composite(pose,(0,int(offset)))
                    else:
                        moved=clear_transparent_rgb(pose.convert('RGBa').transform((192,208),Image.Transform.AFFINE,
                            (1,0,0,0,1,-offset),resample=Image.Resampling.BICUBIC).convert('RGBA'))
                    frame.paste(moved,(box[0],box[1]))
        frames.append(frame)
    output=Path(output)
    frames[0].save(output,format='PNG',save_all=True,append_images=frames[1:],duration=list(DURATIONS),
                   loop=0,disposal=0,blend=0)
    assert output.stat().st_size<=20*1024*1024,'Native image exceeds the supported size limit.'
    with Image.open(output) as encoded:
        assert encoded.n_frames==4,'Temporal phases were lost during encoding.'
        for index in range(encoded.n_frames):
            encoded.seek(index)
            actual=encoded.convert('RGBA')
            assert actual.tobytes()==frames[index].tobytes(),'PNG encoding changed approved pixels.'
            assert actual.crop((0,0,1536,1872)).tobytes()==base.crop((0,0,1536,1872)).tobytes()
    return {'ok':True,'mode':'local-apng-gaze-breath','container_frames':4,'cycle_ms':sum(DURATIONS),
            'gaze_vertical_offsets_px':list(OFFSETS),'standard57_cells_pixel_identical_in_every_phase':True,
            'first_frame_pixel_identical_to_source':True,'source_art_redrawn':False,
            'bytes':output.stat().st_size,'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
            'reduced_motion_note':'Encoded gaze-cell animation is not stopped by the native JS frame timer.'}


def webp_chunk(kind, data):
    return kind+struct.pack('<I',len(data))+data+(b'\0' if len(data)%2 else b'')


def exact_webp_image_chunks(image):
    buffer=io.BytesIO()
    image.save(buffer,format='WEBP',lossless=True,quality=100,exact=True,method=4)
    encoded=buffer.getvalue()
    offset,parts=12,[]
    while offset<len(encoded):  # RIFF is a sequential variable-length chunk format.
        size,=struct.unpack_from('<I',encoded,offset+4)
        kind=encoded[offset:offset+4]
        if kind in (b'VP8L',b'VP8 ',b'ALPH'):
            parts.append(encoded[offset:offset+8+size+size%2])
        offset+=8+size+size%2
    return b''.join(parts)


def encode_fast_gaze_breath(source,output):
    """Exact lossless RIFF frames update idle and look strips separately, avoiding full-atlas copies."""
    base=Image.open(source).convert('RGBA')
    assert base.size==(1536,2288)
    uint24=lambda value:int(value).to_bytes(3,'little')
    parts=[webp_chunk(b'VP8X',bytes((0x12,0,0,0))+uint24(1535)+uint24(2287)),
           webp_chunk(b'ANIM',b'\0'*6)]
    expected=[]
    for phase,(offset,duration) in enumerate(zip(OFFSETS,DURATIONS)):
        frame=base.copy()
        if offset:
            for row,columns in ((0,6),(9,8),(10,8)):
                for column in range(columns):
                    box=(column*192,row*208,(column+1)*192,(row+1)*208)
                    moved=clear_transparent_rgb(base.crop(box).convert('RGBa').transform((192,208),Image.Transform.AFFINE,
                        (1,0,0,0,1,-offset),resample=Image.Resampling.BICUBIC).convert('RGBA'))
                    frame.paste(moved,(box[0],box[1]))
        # Both strips persist between frames. >=25ms avoids browser short-frame clamping.
        rectangles=[((0,0,1536,2288),duration)] if phase==0 else [((0,0,1536,208),25),((0,1872,1536,2288),duration-25)]
        composite=base.copy() if phase==0 else expected[-1].copy()
        for (left,top,right,bottom),pause in rectangles:
            cropped=frame.crop((left,top,right,bottom))
            header=uint24(left//2)+uint24(top//2)+uint24(right-left-1)+uint24(bottom-top-1)+uint24(pause)+b'\x02'
            parts.append(webp_chunk(b'ANMF',header+exact_webp_image_chunks(cropped)))
            composite.paste(cropped,(left,top))
            expected.append(composite.copy())
    payload=b'WEBP'+b''.join(parts)
    output=Path(output)
    output.write_bytes(b'RIFF'+struct.pack('<I',len(payload))+payload)
    assert output.stat().st_size<=20*1024*1024
    decoded=Image.open(output)
    assert decoded.n_frames==len(expected)==7
    for index,image in enumerate(expected):
        decoded.seek(index)
        actual=decoded.convert('RGBA')
        assert actual.tobytes()==image.tobytes(),'Lossless animation altered pixels, including transparent RGB.'
        assert actual.crop((0,208,1536,1872)).tobytes()==base.crop((0,208,1536,1872)).tobytes()
    return {'ok':True,'mode':'local-exact-webp-gaze-breath','container_frames':7,'cycle_ms':sum(DURATIONS),
            'gaze_vertical_offsets_px':list(OFFSETS),'native_action_rows_pixel_identical_in_every_phase':True,
            'idle_columns_share_pose_and_container_breath_clock':True,'first_frame_pixel_identical_to_source':True,
            'source_art_redrawn':False,'bytes':output.stat().st_size,'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}


def encode_hover_action(source,poses,durations,output,loops=1):
    """Animate the same pose in every native idle/hover column; preserve all other native rows."""
    base=Image.open(source).convert('RGBA')
    assert base.size==(1536,2288) and len(poses)==len(durations)
    uint24=lambda value:int(value).to_bytes(3,'little')
    parts=[webp_chunk(b'VP8X',bytes((0x12,0,0,0))+uint24(1535)+uint24(2287)),
           webp_chunk(b'ANIM',b'\0'*4+int(loops).to_bytes(2,'little'))]
    expected=[]
    composite=base.copy()
    for phase,(pose,duration) in enumerate(zip(poses,durations)):
        assert pose.size==(192,208) and duration>=50
        frame=base.copy()
        for row,columns in ((0,6),(4,5)):
            for column in range(columns):
                frame.paste(pose,(column*192,row*208))
        rectangles=[((0,0,1536,2288),duration)] if phase==0 else [((0,0,1536,208),25),((0,832,1536,1040),duration-25)]
        for (left,top,right,bottom),pause in rectangles:
            cropped=frame.crop((left,top,right,bottom))
            header=uint24(left//2)+uint24(top//2)+uint24(right-left-1)+uint24(bottom-top-1)+uint24(pause)+b'\x02'
            parts.append(webp_chunk(b'ANMF',header+exact_webp_image_chunks(cropped)))
            composite.paste(cropped,(left,top))
            expected.append(hashlib.sha256(composite.tobytes()).hexdigest())
    payload=b'WEBP'+b''.join(parts)
    output=Path(output)
    output.write_bytes(b'RIFF'+struct.pack('<I',len(payload))+payload)
    assert output.stat().st_size<20*1024*1024
    encoded=Image.open(output)
    assert encoded.n_frames==len(expected) and encoded.info['loop']==loops
    for index,digest in enumerate(expected):
        encoded.seek(index)
        assert hashlib.sha256(encoded.convert('RGBA').tobytes()).hexdigest()==digest
    return {'ok':True,'file':output.name,'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
            'bytes':output.stat().st_size,'container_frames':encoded.n_frames,'pose_frames':len(poses),
            'cycle_ms':sum(durations),'loops':loops,'duration_ms':sum(durations)*loops,
            'preserved_rows':[1,2,3,5,6,7,8,9,10],
            'custom_hover_rows':[0,4],'decoded_pixels_including_transparent_rgb_exact':True}


if __name__=='__main__':
    import sys
    report=encode_look_breath(sys.argv[1],sys.argv[2])
    if len(sys.argv)>3:
        Path(sys.argv[3]).write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))
