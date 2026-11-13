import json
import re
import shutil
from pathlib import Path

import imageio_ffmpeg
import yt_dlp

from .extract import extract

SONGS_DIR = Path(__file__).resolve().parents[2] / "songs"


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:60] or "song"


def song_dir(song_id):
    path = (SONGS_DIR / song_id).resolve()
    if path.parent != SONGS_DIR.resolve():
        raise ValueError("bad song id")
    return path


def read_song(song_id):
    path = song_dir(song_id)
    meta = path / "song.json"
    song = json.loads(meta.read_text()) if meta.exists() else {"id": song_id, "title": song_id.replace("_", " ").title()}
    if "status" not in song:
        song["status"] = "ready" if (path / "choreography.json").exists() else "new"
    return song


def write_song(song_id, **fields):
    path = song_dir(song_id)
    path.mkdir(parents=True, exist_ok=True)
    song = read_song(song_id) | fields
    (path / "song.json").write_text(json.dumps(song, indent=2))
    return song


def list_songs():
    if not SONGS_DIR.exists():
        return []
    return [read_song(p.name) for p in sorted(SONGS_DIR.iterdir()) if (p / "video.mp4").exists() or (p / "song.json").exists()]


def new_song_id(title):
    base, n = slug(title), 1
    song_id = base
    while song_dir(song_id).exists():
        n += 1
        song_id = f"{base}_{n}"
    return song_id


def reporter(song_id):
    last = [-1]

    def report(p):
        step = int(min(p, 1) * 20)
        if step != last[0]:
            last[0] = step
            write_song(song_id, progress=step / 20)

    return report


def download_youtube(url, song_id):
    path = song_dir(song_id)
    path.mkdir(parents=True, exist_ok=True)
    report = reporter(song_id)
    options = {
        "outtmpl": str(path / "video.%(ext)s"),
        "format": "bv*[ext=mp4][height<=1080]+ba[ext=m4a]/b[ext=mp4]/b",
        "ffmpeg_location": shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe(),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "noprogress": True,
        "js_runtimes": {"node": {"path": shutil.which("node")}} if shutil.which("node") else {},
        "progress_hooks": [lambda d: report(d.get("downloaded_bytes", 0) / (d.get("total_bytes") or d.get("total_bytes_estimate") or 1))],
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
    files = [f for f in path.glob("video.*") if f.suffix != ".part"]
    if files and files[0].name != "video.mp4":
        files[0].rename(path / "video.mp4")
    return info


def process(song_id):
    path = song_dir(song_id)
    write_song(song_id, status="extracting", progress=0, error=None)
    try:
        song = read_song(song_id)
        stats = extract(path / "video.mp4", dancers=song.get("dancers", 1), on_progress=reporter(song_id), members=song.get("members"), ignore=song.get("ignore", ()))
        return write_song(song_id, status="ready", progress=1, **stats)
    except Exception as e:
        write_song(song_id, status="failed", error=str(e))
        raise


def ingest_youtube(url, song_id):
    write_song(song_id, status="downloading", progress=0, source_url=url)
    try:
        info = download_youtube(url, song_id)
        write_song(song_id, title=info.get("title") or song_id, youtube_id=info.get("id"))
    except Exception as e:
        write_song(song_id, status="failed", error=str(e))
        raise
    return process(song_id)
