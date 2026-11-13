# Just Dance Better

Turn a dance video (a file or a YouTube link) into a playable routine scored live with your webcam.

## Layout

- `backend/` Python: dancer tracking and pose extraction, and the song API (FastAPI)
- `frontend/` React game (Phase 2, not built yet)
- `songs/<id>/` one folder per song: `video.mp4`, `choreography.json`, `song.json`

## Backend setup

Tested with Python 3.13.

```bash
cd backend
python3.13 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Models download on first run: YOLO segmentation and the MediaPipe pose model to `backend/models/`, DINOv2 to the Hugging Face cache. YouTube downloads use a bundled ffmpeg, and Node.js if installed, so nothing else is needed.

## Run the API

```bash
cd backend
.venv/bin/uvicorn dance.api:app --reload
```

- `GET /songs` list songs
- `GET /songs/{id}` song info and processing status
- `GET /songs/{id}/video` the video
- `GET /songs/{id}/choreography` the pose timeline
- `POST /songs/youtube` `{"url": "...", "title": "...", "dancers": 9}` download and extract in the background
- `POST /songs/upload` form fields `file`, `title`, `dancers`
- `POST /songs/{id}/extract?dancers=9` re-run extraction
- `GET /debug/{id}` skeleton drawn over the video, to check tracking by eye

## Extract from the command line

```bash
cd backend
.venv/bin/python -m dance.extract ../songs/<id>/video.mp4 --fps 30 --dancers 9
```

## How tracking works

1. YOLO segmentation finds every person in each frame and cuts out their outline.
2. Each person gets an appearance fingerprint from inside the outline only: colour histograms of hair, top, trousers and shoes, plus DINOv2 features. The background is ignored, so moving to a new spot does not change who someone is.
3. MediaPipe Pose runs on each person with everyone else masked out, giving 33 body points.
4. Frame-to-frame box overlap builds short, certain track pieces. Pieces break whenever people overlap or their look changes.
5. The pieces are joined into the requested number of dancers. A moment where every dancer is clearly visible fixes the IDs (numbered left to right). A per-video classifier then learns each dancer's look, matches the other clear moments to them, and labels the remaining pieces, never giving one dancer two places at once.
6. Gaps during crossings are filled from detections that fit both the expected position and the dancer's look, and every remaining gap is bridged: the dancer gets a neutral standing figure (arms by her side) placed where she is in the group, marked as estimated.

## Cleaning up poses

After tracking, each dancer's poses are repaired before the file is written:

- A skeleton that collapses (much shorter than the dancer's box, or suddenly short with hidden legs) or briefly hops onto a neighbour is rebuilt from the poses just before and after. If the gap is longer than a second, a standing figure is placed on the dancer's box.
- Arms and legs are capped at 1.4× their usual length.
- Hidden joints move with the body instead of freezing in place.
- A hidden dancer's standing figure is sized to the dancers around her and placed on a nearby untracked person, or stacked behind the nearest tracked dancer.
- `ignore` in `song.json` lists regions the tracker should skip, such as mirrors: `[x0, y0, x1, y1]` in fractions of the frame, optionally followed by a start and end time in seconds.

## Choreography format

```json
{
  "song_id": "what_is_love_twice",
  "version": 2,
  "fps": 30, "width": 2520, "height": 1080,
  "min_visibility": 0.5, "landmarks": 33, "dancers": 9,
  "frames": [{"t": 0.033, "d": [[[x, y, visibility], ...], ...], "e": [3]}]
}
```

Each frame's `d` has one entry per dancer, always in the same order: 33 MediaPipe Pose points normalised to the video's width and height, smoothed, in the video's own orientation (source videos are mirrored dance practice uploads, so the player copies the screen like a mirror), `e` lists the dancers whose pose in that frame is estimated (a standing placeholder while she is hidden or stacked behind others), so the game can skip scoring them. Points under `min_visibility` are low confidence.

## Measuring tracking accuracy

`backend/eval/labels/` holds hand-checked answers for the four 30 second test clips (`songs/*_test_30s`): 20 moments × 9 members each, plus which members are fully hidden. A member counts as correct when her ID sits on her, and hidden members are left out.

```bash
cd backend
.venv/bin/python eval/score.py score <run.pkl> eval/labels/tt.json
.venv/bin/python eval/frameview.py ../songs/tt_test_30s/video.mp4 <run.pkl> out.jpg 2.0 3.5
```

Current: What Is Love 98.9%, TT 94.6%, This Is For 93.9%, Fancy 89.8% (94.4% overall). It's about 96% when gaps under a second are bridged, which the choreography output does.
