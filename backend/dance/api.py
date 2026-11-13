import json
import shutil
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import library

JOINTS = [0, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]
STATIC = Path(__file__).resolve().parents[1] / "static"

app = FastAPI(title="Just Dance Better")
rooms = defaultdict(dict)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])


class YoutubeRequest(BaseModel):
    url: str
    title: str | None = None
    dancers: int = 1


def existing(song_id, name=None):
    try:
        path = library.song_dir(song_id)
    except ValueError:
        raise HTTPException(400, "bad song id")
    target = path / name if name else path
    if not target.exists():
        raise HTTPException(404, "not found")
    return target


@app.get("/songs")
def songs():
    return library.list_songs()


@app.get("/songs/{song_id}")
def song(song_id: str):
    existing(song_id)
    return library.read_song(song_id)


@app.get("/songs/{song_id}/video")
def video(song_id: str):
    return FileResponse(existing(song_id, "video.mp4"), media_type="video/mp4")


@app.get("/songs/{song_id}/choreography")
def choreography(song_id: str):
    return FileResponse(existing(song_id, "choreography.json"), media_type="application/json")


@lru_cache(maxsize=2)
def load_moves(path, modified):
    data = json.loads(Path(path).read_text())
    frames = data["frames"]
    return {
        "fps": data["fps"],
        "aspect": data["width"] / data["height"],
        "min_visibility": data["min_visibility"],
        "names": data.get("names") or [str(i + 1) for i in range(data["dancers"])],
        "t": [f["t"] for f in frames],
        "e": [f.get("e", []) for f in frames],
        "d": [[[[round(v, 3) for v in f["d"][d][j]] for j in JOINTS] for f in frames] for d in range(data["dancers"])],
    }


@app.get("/songs/{song_id}/moves")
def moves(song_id: str, dancers: str):
    path = existing(song_id, "choreography.json")
    data = load_moves(str(path), path.stat().st_mtime)
    try:
        picked = sorted({int(d) for d in dancers.split(",")})
        poses = {d: data["d"][d] for d in picked}
    except (ValueError, IndexError):
        raise HTTPException(400, "bad dancers")
    return {**{k: data[k] for k in ("fps", "aspect", "min_visibility", "names", "t")}, "e": [[d in e for e in data["e"]] for d in picked], "dancers": picked, "d": [poses[d] for d in picked]}


@app.websocket("/rooms/{code}")
async def room(socket: WebSocket, code: str, device: str):
    await socket.accept()
    members = rooms[code]
    members[device] = socket

    async def send(message, skip):
        for name, other in list(members.items()):
            if name != skip:
                try:
                    await other.send_text(message)
                except Exception:
                    members.pop(name, None)

    try:
        while True:
            await send(await socket.receive_text(), device)
    except WebSocketDisconnect:
        pass
    finally:
        if members.get(device) is socket:
            del members[device]
        await send(json.dumps({"type": "left", "device": device}), device)
        if not members:
            rooms.pop(code, None)


@app.get("/model")
def model():
    path = STATIC.parent / "models" / "pose_landmarker_full.task"
    if not path.exists():
        raise HTTPException(404, "not found")
    return FileResponse(path)


@app.post("/songs/upload", status_code=202)
def upload(background: BackgroundTasks, file: UploadFile = File(...), title: str = Form(...), dancers: int = Form(1)):
    song_id = library.new_song_id(title)
    path = library.song_dir(song_id)
    path.mkdir(parents=True)
    with open(path / "video.mp4", "wb") as out:
        shutil.copyfileobj(file.file, out)
    song = library.write_song(song_id, title=title, dancers=dancers, status="queued")
    background.add_task(library.process, song_id)
    return song


@app.post("/songs/youtube", status_code=202)
def youtube(request: YoutubeRequest, background: BackgroundTasks):
    song_id = library.new_song_id(request.title or "youtube")
    song = library.write_song(song_id, title=request.title or song_id, dancers=request.dancers, status="queued", source_url=request.url)
    background.add_task(library.ingest_youtube, request.url, song_id)
    return song


@app.post("/songs/{song_id}/extract", status_code=202)
def reextract(song_id: str, background: BackgroundTasks, dancers: int | None = None):
    existing(song_id, "video.mp4")
    song = library.write_song(song_id, status="queued", **({"dancers": dancers} if dancers else {}))
    background.add_task(library.process, song_id)
    return song


@app.get("/debug/{song_id}")
def debug(song_id: str):
    existing(song_id)
    return FileResponse(STATIC / "debug.html")
