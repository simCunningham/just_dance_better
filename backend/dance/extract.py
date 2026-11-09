import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from .tracking import Scanner, identities

MIN_VISIBILITY = 0.5
MAX_FILL = 2.0


def detect(video_path, fps, dancers, on_progress=None):
    cap = cv2.VideoCapture(str(video_path))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    scan = Scanner()
    times, people = [], []
    next_t, index = 0.0, 0
    while cap.grab():
        t = index / src_fps
        index += 1
        if t + 1e-6 < next_t:
            continue
        next_t += 1 / fps
        _, frame = cap.retrieve()
        found = scan(frame)
        for p in found:
            p["emb"] = p["emb"].astype(np.float16)
        times.append(t)
        people.append(found)
        if on_progress and total:
            on_progress(min(index / total, 1) * 0.95)
    cap.release()
    owner = identities(times, people, dancers)
    frames = [[None if j is None else people[f][j]["pose"] for j in row] for f, row in enumerate(owner)]
    frames, estimated = fill(times, frames, dancers)
    return times, frames, estimated, width, height


def fill(times, frames, dancers):
    estimated = [[] for _ in times]
    for d in range(dancers):
        seen = [f for f in range(len(times)) if frames[f][d] is not None]
        for a, b in zip(seen, seen[1:]):
            if b - a > 1 and times[b] - times[a] <= MAX_FILL:
                for f in range(a + 1, b):
                    k = (times[f] - times[a]) / (times[b] - times[a])
                    frames[f][d] = frames[a][d] * (1 - k) + frames[b][d] * k
                    estimated[f].append(d)
    return frames, estimated


def segments(poses):
    start = None
    for i, p in enumerate(poses + [None]):
        if p is not None and start is None:
            start = i
        elif p is None and start is not None:
            yield start, i
            start = None


def smooth(poses, alpha):
    poses = list(poses)
    for a, b in segments(poses):
        held = np.stack(poses[a:b])
        for i in range(1, len(held)):
            low = held[i, :, 2] < MIN_VISIBILITY
            held[i, low, :2] = held[i - 1, low, :2]
        out = held.copy()
        for i in range(1, len(out)):
            out[i, :, :2] = alpha * held[i, :, :2] + (1 - alpha) * out[i - 1, :, :2]
        for i in range(len(out) - 2, -1, -1):
            out[i, :, :2] = alpha * out[i, :, :2] + (1 - alpha) * out[i + 1, :, :2]
        poses[a:b] = list(out)
    return poses


def frame(t, tracks, i, estimated):
    out = {"t": round(t, 3), "d": [None if tr[i] is None else np.round(tr[i], 4).tolist() for tr in tracks]}
    if estimated:
        out["e"] = estimated
    return out


def build(song_id, times, frames, estimated, width, height, fps, dancers, alpha):
    tracks = [smooth([f[d] for f in frames], alpha) for d in range(dancers)]
    return {
        "song_id": song_id,
        "version": 2,
        "fps": fps,
        "width": width,
        "height": height,
        "min_visibility": MIN_VISIBILITY,
        "landmarks": 33,
        "dancers": dancers,
        "frames": [frame(t, tracks, i, estimated[i]) for i, t in enumerate(times)],
    }


def extract(video_path, out_path=None, fps=30, dancers=1, alpha=0.5, on_progress=None):
    video_path = Path(video_path)
    out_path = Path(out_path or video_path.with_name("choreography.json"))
    times, frames, estimated, width, height = detect(video_path, fps, dancers, on_progress)
    out_path.write_text(json.dumps(build(video_path.parent.name, times, frames, estimated, width, height, fps, dancers, alpha), separators=(",", ":")))
    tracked = [sum(f[d] is not None for f in frames) for d in range(dancers)]
    guessed = [sum(d in e for e in estimated) for d in range(dancers)]
    return {"frames": len(frames), "tracked": tracked, "estimated": guessed, "duration": round(times[-1], 3) if times else 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video")
    parser.add_argument("-o", "--out")
    parser.add_argument("--fps", type=float, default=30)
    parser.add_argument("--dancers", type=int, default=1)
    parser.add_argument("--alpha", type=float, default=0.5)
    args = parser.parse_args()
    last = [-1]

    def progress(p):
        pct = int(p * 100)
        if pct != last[0]:
            last[0] = pct
            print(f"\r{pct}%", end="", flush=True)

    print(f"\n{extract(args.video, args.out, args.fps, args.dancers, args.alpha, progress)}")


if __name__ == "__main__":
    main()
