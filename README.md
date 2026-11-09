# Just Dance Better

Turn a dance video (a file or a YouTube link) into a playable routine scored live with your webcam.

## Layout

- `backend/` Python: pose extraction (MediaPipe) and the song API (FastAPI)
- `frontend/` React game (Phase 2, not built yet)
- `songs/<id>/` one folder per song: `video.mp4`, `choreography.json`, `song.json`

## Backend setup

Tested with Python 3.13.

```bash
cd backend
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

The pose model downloads to `backend/models/` on first run. YouTube downloads use a bundled ffmpeg, and Node.js if installed, so nothing else is needed.

## Run the API

```bash
cd backend
.venv/bin/uvicorn dance.api:app --reload
```

- `GET /songs` list songs
- `GET /songs/{id}` song info and processing status
- `GET /songs/{id}/video` the video
- `GET /songs/{id}/choreography` the pose timeline
- `POST /songs/youtube` `{"url": "...", "title": "..."}` download and extract in the background
- `POST /songs/upload` form fields `file` and `title`
- `POST /songs/{id}/extract` re-run extraction
- `GET /debug/{id}` skeleton drawn over the video, to check tracking by eye

## Extract from the command line

```bash
cd backend
.venv/bin/python -m dance.extract ../songs/<id>/video.mp4 --fps 30
```

## Choreography format

```json
{
  "song_id": "this_is_for_twice",
  "fps": 30, "width": 2520, "height": 1080,
  "mirrored": true, "min_visibility": 0.5, "landmarks": 33,
  "frames": [{"t": 0.033, "p": [[x, y, visibility], ...], "low": [15, 16]}]
}
```

`p` holds the 33 MediaPipe Pose points, normalised to the video's width and height, smoothed and mirrored left to right so the player copies the screen like a mirror. `low` lists points under `min_visibility`, and `p` is `null` when no dancer was found. In group videos the extractor follows the dancer nearest the centre at the start.
