"""Extract a tWAV resource and probe it with ffmpeg to determine format."""
import sys, os, subprocess, tempfile
sys.path.insert(0, r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven")
import riven_img as R

GAME = r"C:\Users\lukea\Games\Steam Library\steamapps\common\Riven"
TWAV = b"tWAV"

for fname in ["a_sounds.mhk", "j_sounds.mhk", "a_data.mhk", "b_data.mhk"]:
    arc = R.Archive(os.path.join(GAME, fname))
    ids = arc.ids(TWAV)
    if not ids:
        continue
    rid = ids[0]
    data = arc.read(TWAV, rid)
    with tempfile.NamedTemporaryFile(suffix=".mhk", delete=False) as f:
        f.write(data)
        tmp = f.name
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", tmp],
            capture_output=True, text=True, timeout=10
        )
        print(f"{fname} rid={rid} size={len(data)}")
        print(r.stdout[:600] or r.stderr[:200])
    except FileNotFoundError:
        # try full path
        for ffprobe in [r"C:\ffmpeg\bin\ffprobe.exe", r"C:\Program Files\ffmpeg\bin\ffprobe.exe"]:
            if os.path.exists(ffprobe):
                r = subprocess.run([ffprobe, "-v","quiet","-print_format","json","-show_streams",tmp],
                                   capture_output=True, text=True, timeout=10)
                print(f"{fname} rid={rid}: {r.stdout[:400] or r.stderr[:200]}")
                break
        else:
            # Try hex analysis of the inner MHWK bytes
            print(f"{fname} rid={rid} size={len(data)}")
            print(f"  bytes 0-63: {data[:64].hex()}")
    finally:
        os.unlink(tmp)
