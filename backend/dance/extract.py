import argparse
import json
import pickle
from pathlib import Path

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

from .tracking import Scanner, identities

MIN_VISIBILITY = 0.5
FLOOR_BAND = 0.06
SQUASH_RATIO = 0.65
SQUASH_WINDOW = 30
SQUASH_GAP = 1.0
BOX_MARGIN = 0.1
BOX_SPAN = 0.6
JUMP = 0.15
JUMP_WINDOW = 4
STRETCH = 1.4
BONES = [(11, 13, [15, 17, 19, 21]), (13, 15, [17, 19, 21]), (12, 14, [16, 18, 20, 22]), (14, 16, [18, 20, 22]), (23, 25, [27, 29, 31]), (25, 27, [29, 31]), (24, 26, [28, 30, 32]), (26, 28, [30, 32])]
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
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    size = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    scanner = Scanner()
    times, people = [], []
    next_t, index = 0.0, 0
    while cap.grab():
        t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
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


def outside(person, t, ignore, width, height):
    x, y = (person["box"][0] + person["box"][2]) / 2 / width, (person["box"][1] + person["box"][3]) / 2 / height
    return not any(x0 <= x <= x1 and y0 <= y <= y1 and (not span or span[0] <= t <= span[1]) for x0, y0, x1, y1, *span in ignore)


def detect(video_path, fps, dancers, on_progress=None, ignore=()):
    times, people, (width, height) = scan(video_path, fps, on_progress)
    people = [[p for p in found if outside(p, t, ignore, width, height)] for t, found in zip(times, people)]
    owner = identities(times, people, dancers)
    frames = [[None if j is None else people[f][j]["pose"] for j in row] for f, row in enumerate(owner)]
    boxes = [[None if j is None else people[f][j]["box"] / [width, height, width, height] for j in row] for f, row in enumerate(owner)]
    repaired, anchors = repair(times, frames, boxes, dancers, height / width)
    clamp_limbs(frames, dancers, height / width)
    spare = [[((p["box"][0] + p["box"][2]) / 2 / width, p["box"][3] / height) for j, p in enumerate(found) if j not in row] for found, row in zip(people, owner)]
    frames, estimated = fill(times, frames, dancers, height / width, spare, anchors)
    for f, d in repaired:
        estimated[f].append(d)
    return times, frames, estimated, width, height


def clamp_limbs(frames, dancers, aspect):
    scale = np.array([1 / aspect, 1])
    for d in range(dancers):
        seen = [f for f in range(len(frames)) if frames[f][d] is not None]
        if not seen:
            continue
        poses = np.stack([frames[f][d] for f in seen])
        for parent, child, rest in BONES:
            length = np.linalg.norm((poses[:, child, :2] - poses[:, parent, :2]) * scale, axis=1)
            limit = STRETCH * np.median(length)
            for i in np.flatnonzero(length > limit):
                shift = (poses[i, child, :2] - poses[i, parent, :2]) * (limit / length[i] - 1)
                poses[i, [child, *rest], :2] += shift
        for f, pose in zip(seen, poses):
            frames[f][d] = pose


def misplaced(pose, box):
    x0, y0, x1, y1 = box
    mx, my = (x1 - x0) * BOX_MARGIN, (y1 - y0) * BOX_MARGIN
    torso = pose[[11, 12, 23, 24], :2]
    inside = (torso[:, 0] > x0 - mx) & (torso[:, 0] < x1 + mx) & (torso[:, 1] > y0 - my) & (torso[:, 1] < y1 + my)
    return inside.sum() < 3 or not x0 < torso[:, 0].mean() < x1


def onto(pose, box):
    pose = pose.copy()
    low, high = pose[:, :2].min(0), pose[:, :2].max(0)
    pose[:, 0] += (box[0] + box[2]) / 2 - (low[0] + high[0]) / 2
    pose[:, 1] += box[3] - high[1]
    return pose


def repair(times, frames, boxes, dancers, aspect):
    repaired, anchors = [], {}
    for d in range(dancers):
        seen = [f for f in range(len(times)) if frames[f][d] is not None]
        span = np.array([frames[f][d][[27, 28], 1].mean() - frames[f][d][[11, 12], 1].mean() for f in seen])
        legs = np.array([frames[f][d][25:29, 2].min() for f in seen])
        usual = np.array([np.median(span[max(0, i - SQUASH_WINDOW):i + SQUASH_WINDOW + 1]) for i in range(len(seen))])
        off = np.array([misplaced(frames[f][d], boxes[f][d]) for f in seen], bool)
        hips = np.array([frames[f][d][[23, 24], :2].mean(0) for f in seen]) / [aspect, 1]
        path = np.array([np.median(hips[max(0, i - JUMP_WINDOW):i + JUMP_WINDOW + 1], axis=0) for i in range(len(seen))])
        hop = np.linalg.norm(hips - path, axis=1) > JUMP * usual
        short = np.array([np.ptp(frames[f][d][:, 1]) < BOX_SPAN * (boxes[f][d][3] - boxes[f][d][1]) for f in seen], bool)
        bad = (span < SQUASH_RATIO * usual) & (legs < MIN_VISIBILITY) | short | off | hop
        shift = dict(zip(seen, off))
        good = [f for f, b in zip(seen, bad) if not b]
        for f in (f for f, b in zip(seen, bad) if b):
            k = int(np.searchsorted(good, f))
            if 0 < k < len(good) and times[good[k]] - times[good[k - 1]] <= SQUASH_GAP:
                a, b = good[k - 1], good[k]
                w = (times[f] - times[a]) / (times[b] - times[a])
                frames[f][d] = frames[a][d] * (1 - w) + frames[b][d] * w
                if shift[f]:
                    frames[f][d] = onto(frames[f][d], boxes[f][d])
                repaired.append((f, d))
            else:
                frames[f][d] = None
                anchors[f, d] = boxes[f][d]
    return repaired, anchors


def standing(x, feet, tall, aspect):
    pose = np.ones((33, 3))
    pose[:, 0] = x + STANDING[:, 0] * tall * aspect
    pose[:, 1] = feet - (1 - STANDING[:, 1]) * tall
    return pose


def behind(x, feet, shown, spare, reach):
    near = [(abs(sx - x), sx, sy) for sx, sy in spare if abs(sx - x) < reach]
    if near:
        return min(near)[1:]
    hips = [(abs(p[[23, 24], 0].mean() - x), p[[23, 24], 0].mean(), feet) for p in shown]
    return min(hips)[1:] if hips else (x, feet)


def fill(times, frames, dancers, aspect, spare, anchors):
    estimated = [[] for _ in times]
    shown = [[p for p in row if p is not None] for row in frames]
    spans = [p[[27, 28], 1].mean() - p[[11, 12], 1].mean() for row in frames for p in row if p is not None]
    typical = np.median(spans) if spans else 0
    local = [np.median([p[[27, 28], 1].mean() - p[[11, 12], 1].mean() for p in row if p is not None]) if sum(p is not None for p in row) >= 3 else None for row in frames]
    local = [np.median([v for v in local[max(0, f - 15):f + 16] if v] or [0]) for f in range(len(times))]
    floor = [np.median([p[[27, 28], 1].mean() for p in row if p is not None]) if any(p is not None for p in row) else None for row in frames]
    for d in range(dancers):
        seen = [f for f in range(len(times)) if frames[f][d] is not None]
        if not seen:
            continue
        spot = np.array([[frames[f][d][[23, 24], 0].mean(), frames[f][d][[27, 28], 1].mean(), frames[f][d][[27, 28], 1].mean() - frames[f][d][[11, 12], 1].mean()] for f in seen])
        for f in range(len(times)):
            if frames[f][d] is not None:
                continue
            tall = (local[f] or min(np.median(spot[:, 2]), typical)) / 0.8
            x, feet = (np.interp(times[f], [times[g] for g in seen], spot[:, i]) for i in (0, 1))
            if floor[f] is not None:
                feet = np.clip(feet, floor[f] - FLOOR_BAND, floor[f] + FLOOR_BAND)
            feet += 0.06 * tall
            x, feet = behind(x, feet, shown[f], spare[f], tall * aspect)
            if (f, d) in anchors:
                x0, y0, x1, y1 = anchors[f, d]
                x, feet, tall = (x0 + x1) / 2, y1, (y1 - y0) * 0.95
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
        core = held[:, [11, 12, 23, 24], :2].mean(1)
        for i in range(1, len(held)):
            low = held[i, :, 2] < MIN_VISIBILITY
            held[i, low, :2] = held[i - 1, low, :2] + core[i] - core[i - 1]
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


def name_dancers(times, frames, members, width, height):
    row = frames[int(np.argmin(np.abs(np.array(times) - members["t"])))]
    boxes = np.array(members["boxes"]) / [width, height, width, height]
    spots = np.array([[p[[23, 24], 0].mean(), p[[11, 12, 23, 24], 1].mean()] for p in row])
    centers = np.stack([(boxes[:, 0] + boxes[:, 2]) / 2, boxes[:, 1] * 0.6 + boxes[:, 3] * 0.4], 1)
    cost = np.linalg.norm(spots[:, None] - centers[None], axis=2)
    names = [None] * len(row)
    for d, b in zip(*linear_sum_assignment(cost)):
        names[d] = members["names"][b]
    return names


def extract(video_path, out_path=None, fps=30, dancers=1, alpha=0.5, on_progress=None, members=None, ignore=()):
    video_path = Path(video_path)
    out_path = Path(out_path or video_path.with_name("choreography.json"))
    times, frames, estimated, width, height = detect(video_path, fps, dancers, on_progress, ignore)
    data = build(video_path.parent.name, times, frames, estimated, width, height, fps, dancers, alpha)
    if members:
        data["names"] = name_dancers(times, frames, members, width, height)
    out_path.write_text(json.dumps(data, separators=(",", ":")))
    tracked = [sum(f[d] is not None for f in frames) for d in range(dancers)]
    guessed = [sum(d in e for e in estimated) for d in range(dancers)]
    return {"frames": len(frames), "tracked": tracked, "estimated": guessed, "names": data.get("names"), "duration": round(times[-1], 3) if times else 0}


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
