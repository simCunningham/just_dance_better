import shutil
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import library

STATIC = Path(__file__).resolve().parents[1] / "static"

app = FastAPI(title="Just Dance Better")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], allow_methods=["*"], allow_headers=["*"])


class YoutubeRequest(BaseModel):
    url: str
    title: str | None = None


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


@app.post("/songs/upload", status_code=202)
def upload(background: BackgroundTasks, file: UploadFile = File(...), title: str = Form(...)):
    song_id = library.new_song_id(title)
    path = library.song_dir(song_id)
    path.mkdir(parents=True)
    with open(path / "video.mp4", "wb") as out:
        shutil.copyfileobj(file.file, out)
    song = library.write_song(song_id, title=title, status="queued")
    background.add_task(library.process, song_id)
    return song


@app.post("/songs/youtube", status_code=202)
def youtube(request: YoutubeRequest, background: BackgroundTasks):
    song_id = library.new_song_id(request.title or "youtube")
    song = library.write_song(song_id, title=request.title or song_id, status="queued", source_url=request.url)
    background.add_task(library.ingest_youtube, request.url, song_id)
    return song


@app.post("/songs/{song_id}/extract", status_code=202)
def reextract(song_id: str, background: BackgroundTasks):
    existing(song_id, "video.mp4")
    song = library.write_song(song_id, status="queued")
    background.add_task(library.process, song_id)
    return song


@app.get("/debug/{song_id}")
def debug(song_id: str):
    existing(song_id)
    return FileResponse(STATIC / "debug.html")
