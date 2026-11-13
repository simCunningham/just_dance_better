# Just Dance Better

Turn a dance video (a file or a YouTube link) into a playable routine scored live with your webcam.

## Layout

- `backend/` Python: dancer tracking and pose extraction, and the song API (FastAPI)
- `frontend/` React game played with a webcam
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

- `GET /songs/{id}/moves?dancers=0,4` the chosen dancers' poses, trimmed to the 13 joints the game scores
- `GET /model` the pose model the browser uses
- `WS /rooms/{code}?device=...` relays messages between the devices in a room

## Play the game

Tested with Node 22. Start the API, then:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The game plays What Is Love? for now.

1. Choose how many players share this camera (1 to 4) and pick a member for each, on the reference frame or the name buttons. Players stand in order from left to right.
2. The camera check shows when everyone is in full view. Press Start.
3. The video plays with each player's member outlined. Every second each player gets Perfect, Good, OK or Miss from how closely their arms and legs match the member's, and combos add bonus points. Moments when the member is hidden are not scored.
4. The results show scores, rating counts, a timeline of the song and each member's best score on this browser.

### More players on other devices

Every game is a room. Another laptop or phone that opens the join link or scans the QR code can add up to 4 more players on its own camera, 9 players in total. Each device tracks and scores its own players and shares only the scores. The host's video is the clock and the others follow it, muted unless sound is turned on.

Browsers only allow the camera on a secure page, so for devices on the same Wi-Fi run:

```bash
npm run dev:lan
```

and open the `https` Network address it prints on every device, accepting the self-signed certificate warning once.

To play over the internet, point a tunnel such as `cloudflared tunnel --url http://localhost:5173` at `npm run dev` and share the join link from the tunnel's address.

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
