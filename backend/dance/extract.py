import argparse
import json
import urllib.request
from pathlib import Path

import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions, vision

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task"
MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "pose_landmarker_full.task"
MIRROR = [0, 4, 5, 6, 1, 2, 3, 8, 7, 10, 9, 12, 11, 14, 13, 16, 15, 18, 17, 20, 19, 22, 21, 24, 23, 26, 25, 28, 27, 30, 29, 32, 31]
MIN_VISIBILITY = 0.5
MAX_WIDTH = 1280
MAX_JUMP = 0.08
MAX_SPEED = 0.4
REACQUIRE_AFTER = 1.5


def model_path():
    if not MODEL_PATH.exists():
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    return str(MODEL_PATH)


def torso(pose):
    return np.array([[pose[i].x, pose[i].y] for i in (11, 12, 23, 24)])


def pick_dancer(poses, anchor, lost_for):
    torsos = [torso(p) for p in poses]
    dists = [np.abs(t - anchor).mean() if anchor.ndim == 2 else np.linalg.norm(t.mean(0) - anchor) for t in torsos]
    i = int(np.argmin(dists))
    if anchor.ndim == 2 and dists[i] > MAX_JUMP + MAX_SPEED * lost_for and lost_for < REACQUIRE_AFTER:
        return None, anchor
    return poses[i], torsos[i]


def detect(video_path, fps, max_dancers, on_progress=None):
    cap = cv2.VideoCapture(str(video_path))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    scale = min(1, MAX_WIDTH / width)
    options = vision.PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=model_path()),
        running_mode=vision.RunningMode.VIDEO,
        num_poses=max_dancers,
    )
    times, poses = [], []
    anchor, next_t, index, last_seen = np.array([0.5, 0.5]), 0.0, 0, 0.0
    with vision.PoseLandmarker.create_from_options(options) as landmarker:
        while cap.grab():
            t = index / src_fps
            index += 1
            if t + 1e-6 < next_t:
                continue
            next_t += 1 / fps
            _, frame = cap.retrieve()
            if scale < 1:
                frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            result = landmarker.detect_for_video(image, int(t * 1000))
            pose = None
            if result.pose_landmarks:
                chosen, anchor = pick_dancer(result.pose_landmarks, anchor, t - last_seen)
                if chosen is not None:
                    last_seen = t
                    pose = np.array([[p.x, p.y, p.visibility] for p in chosen])
            times.append(t)
            poses.append(pose)
            if on_progress and total:
                on_progress(min(index / total, 1))
    cap.release()
    return times, poses, width, height


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
        seg = np.stack(poses[a:b])
        held = seg.copy()
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


def mirror(pose):
    out = pose[MIRROR].copy()
    out[:, 0] = 1 - out[:, 0]
    return out


def build(song_id, times, poses, width, height, fps):
    frames = []
    for t, p in zip(times, poses):
        if p is None:
            frames.append({"t": round(t, 3), "p": None})
            continue
        p = mirror(p)
        frame = {"t": round(t, 3), "p": np.round(p, 4).tolist()}
        low = np.flatnonzero(p[:, 2] < MIN_VISIBILITY).tolist()
        if low:
            frame["low"] = low
        frames.append(frame)
    return {
        "song_id": song_id,
        "version": 1,
        "fps": fps,
        "width": width,
        "height": height,
        "mirrored": True,
        "min_visibility": MIN_VISIBILITY,
        "landmarks": 33,
        "frames": frames,
    }


def extract(video_path, out_path=None, fps=30, max_dancers=10, alpha=0.5, on_progress=None):
    video_path = Path(video_path)
    out_path = Path(out_path or video_path.with_name("choreography.json"))
    times, poses, width, height = detect(video_path, fps, max_dancers, on_progress)
    data = build(video_path.parent.name, times, smooth(poses, alpha), width, height, fps)
    out_path.write_text(json.dumps(data, separators=(",", ":")))
    tracked = sum(p is not None for p in poses)
    return {"frames": len(poses), "tracked": tracked, "duration": round(times[-1], 3) if times else 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video")
    parser.add_argument("-o", "--out")
    parser.add_argument("--fps", type=float, default=30)
    parser.add_argument("--max-dancers", type=int, default=10)
    parser.add_argument("--alpha", type=float, default=0.5)
    args = parser.parse_args()
    last = [-1]

    def progress(p):
        pct = int(p * 100)
        if pct != last[0]:
            last[0] = pct
            print(f"\r{pct}%", end="", flush=True)

    stats = extract(args.video, args.out, args.fps, args.max_dancers, args.alpha, progress)
    print(f"\n{stats}")


if __name__ == "__main__":
    main()
