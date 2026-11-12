import argparse
import json
import pickle
from pathlib import Path

import cv2
import numpy as np

from .tracking import Scanner, identities

MIN_VISIBILITY = 0.5
FLOOR_BAND = 0.06
SIDES = {1: (0.015, 0.055), 2: (0.02, 0.055), 3: (0.025, 0.055), 7: (0.035, 0.06), 9: (0.015, 0.09), 11: (0.11, 0.19), 13: (0.125, 0.36), 15: (0.13, 0.5), 17: (0.135, 0.54), 19: (0.13, 0.55), 21: (0.12, 0.53), 23: (0.065, 0.52), 25: (0.07, 0.74), 27: (0.07, 0.94), 29: (0.07, 0.97), 31: (0.085, 1.0)}
STANDING = np.zeros((33, 2))
STANDING[0] = 0, 0.07
for left, (x, y) in SIDES.items():
    STANDING[left] = x, y
    STANDING[left + (3 if left < 4 else 1)] = -x, y


def scan(video_path, fps, on_progress=None):
    cache = video_path.with_name("scan.pkl")
    if cache.exists():
        return pickle.loads(cache.read_bytes())
    cap = cv2.VideoCapture(str(video_path))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    size = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    scanner = Scanner()
    times, people = [], []
    next_t, index = 0.0, 0
    while cap.grab():
        t = index / src_fps
        index += 1
        if t + 1e-6 < next_t:
            continue
        next_t += 1 / fps
        _, frame = cap.retrieve()
        found = scanner(frame)
        for p in found:
            p["emb"] = p["emb"].astype(np.float16)
            p["look"] = p["look"].astype(np.float32)
        times.append(t)
        people.append(found)
        if on_progress and total:
            on_progress(min(index / total, 1) * 0.95)
    cap.release()
    result = times, people, size
    cache.write_bytes(pickle.dumps(result))
    return result


def detect(video_path, fps, dancers, on_progress=None):
    times, people, (width, height) = scan(video_path, fps, on_progress)
    owner = identities(times, people, dancers)
    frames = [[None if j is None else people[f][j]["pose"] for j in row] for f, row in enumerate(owner)]
    frames, estimated = fill(times, frames, dancers, height / width)
    return times, frames, estimated, width, height


def standing(x, feet, tall, aspect):
    pose = np.ones((33, 3))
    pose[:, 0] = x + STANDING[:, 0] * tall * aspect
    pose[:, 1] = feet - (1 - STANDING[:, 1]) * tall
    return pose


def fill(times, frames, dancers, aspect):
    estimated = [[] for _ in times]
    spans = [p[[27, 28], 1].mean() - p[[11, 12], 1].mean() for row in frames for p in row if p is not None]
    typical = np.median(spans) if spans else 0
    floor = [np.median([p[[27, 28], 1].mean() for p in row if p is not None]) if any(p is not None for p in row) else None for row in frames]
    for d in range(dancers):
        seen = [f for f in range(len(times)) if frames[f][d] is not None]
        if not seen:
            continue
        spot = np.array([[frames[f][d][[23, 24], 0].mean(), frames[f][d][[27, 28], 1].mean(), frames[f][d][[27, 28], 1].mean() - frames[f][d][[11, 12], 1].mean()] for f in seen])
        tall = min(np.median(spot[:, 2]), typical) / 0.8
        for f in range(len(times)):
            if frames[f][d] is not None:
                continue
            x, feet = (np.interp(times[f], [times[g] for g in seen], spot[:, i]) for i in (0, 1))
            if floor[f] is not None:
                feet = np.clip(feet, floor[f] - FLOOR_BAND, floor[f] + FLOOR_BAND)
            feet += 0.06 * tall
            frames[f][d] = standing(x, feet, tall, aspect)
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
