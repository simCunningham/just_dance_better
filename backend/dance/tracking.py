import urllib.request
from pathlib import Path

import cv2
import numpy as np
import mediapipe as mp
import torch
from mediapipe.tasks.python import BaseOptions, vision
from scipy.optimize import linear_sum_assignment
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from transformers import AutoModel
from ultralytics import YOLO

MODELS = Path(__file__).resolve().parents[1] / "models"
YOLO_URL = "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11m-seg.pt"
POSE_URL = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task"
EMBEDDER = "facebook/dinov2-small"
DEVICE = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)
PARTS = ((0.0, 0.15), (0.15, 0.5), (0.5, 0.88), (0.88, 1.0))
MIN_HEIGHT = 0.5
LINK_IOU = 0.35
CROWD_IOU = 0.25
MAX_LOOK = 0.2
CHAIN_GAP = 0.4
ANCHOR_SPAN = 10.0
RECOVER_IOU = 0.3
RECOVER_PROB = 0.2
RECOVER_GAP = 1.5
OTHER = -1


def fetch(url):
    path = MODELS / url.rsplit("/", 1)[1]
    if not path.exists():
        MODELS.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, path)
    return str(path)


def iou(a, b):
    x0, y0 = np.maximum(a[:2], b[:2])
    x1, y1 = np.minimum(a[2:4], b[2:4])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def center(b):
    return (b[:2] + b[2:4]) / 2


def look_distance(a, b):
    return float(np.mean([1 - np.sum(np.sqrt(x * y)) for x, y in zip(a, b)]))


class Scanner:
    def __init__(self):
        self.yolo = YOLO(fetch(YOLO_URL))
        self.embedder = AutoModel.from_pretrained(EMBEDDER, use_safetensors=True).eval().to(DEVICE)
        options = vision.PoseLandmarkerOptions(base_options=BaseOptions(model_asset_path=fetch(POSE_URL)), num_poses=1)
        self.landmarker = vision.PoseLandmarker.create_from_options(options)

    def __call__(self, frame):
        r = self.yolo.predict(frame, classes=[0], conf=0.3, iou=0.6, imgsz=1280, device=DEVICE, retina_masks=True, verbose=False)[0]
        if r.masks is None:
            return []
        boxes = r.boxes.xyxy.cpu().numpy().astype(float)
        masks = r.masks.data.cpu().numpy() > 0.5
        tall = np.median(boxes[:, 3] - boxes[:, 1])
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        people, crops = [], []
        for box, mask in zip(boxes, masks):
            x0, y0, x1, y1 = box.astype(int)
            inside = mask[y0:y1, x0:x1]
            if box[3] - box[1] < MIN_HEIGHT * tall or not inside.any():
                continue
            people.append({"box": box, "look": self.colors(hsv[y0:y1, x0:x1], inside), "pose": self.pose(frame, box, mask)})
            crop = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2RGB).astype(np.float32) / 255
            crop[~inside] = MEAN
            crops.append(((cv2.resize(crop, (112, 224)) - MEAN) / STD).transpose(2, 0, 1))
        for person, emb in zip(people, self.embed(crops)):
            person["emb"] = emb
        return people

    def colors(self, hsv, mask):
        h, parts = len(mask), []
        for top, bottom in PARTS:
            rows = slice(int(top * h), max(int(bottom * h), int(top * h) + 1))
            sub = mask[rows].astype(np.uint8)
            hist = cv2.calcHist([np.ascontiguousarray(hsv[rows])], [0, 1, 2], sub if sub.any() else None, [12, 4, 4], [0, 180, 0, 256, 0, 256]).flatten()
            parts.append(hist / max(hist.sum(), 1e-6))
        return np.stack(parts)

    @torch.no_grad()
    def embed(self, crops):
        if not crops:
            return []
        out = self.embedder(pixel_values=torch.tensor(np.stack(crops), device=DEVICE)).last_hidden_state
        grid = out[:, 1:].reshape(len(crops), 16, 8, -1)
        return list(torch.cat([out[:, 0], grid[:, :5].mean((1, 2)), grid[:, 5:11].mean((1, 2)), grid[:, 11:].mean((1, 2))], 1).cpu().numpy())

    def pose(self, frame, box, mask):
        h, w = frame.shape[:2]
        side = max(box[2] - box[0], box[3] - box[1]) * 1.2
        cx, cy = center(box)
        x0, y0 = int(max(0, cx - side / 2)), int(max(0, cy - side / 2))
        x1, y1 = int(min(w, cx + side / 2)), int(min(h, cy + side / 2))
        keep = cv2.dilate(mask[y0:y1, x0:x1].astype(np.uint8), np.ones((25, 25), np.uint8)) > 0
        crop = frame[y0:y1, x0:x1].copy()
        crop[~keep] = 128
        result = self.landmarker.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)))
        if not result.pose_landmarks:
            return None
        return np.array([[(x0 + p.x * (x1 - x0)) / w, (y0 + p.y * (y1 - y0)) / h, p.visibility] for p in result.pose_landmarks[0]])


def tracklets(people):
    done, live = [], []
    for f, found in enumerate(people):
        boxes = [p["box"] for p in found]
        busy = [any(i != j and iou(a, b) > CROWD_IOU for j, b in enumerate(boxes)) for i, a in enumerate(boxes)]
        cost = np.ones((len(live), len(boxes)))
        for i, tr in enumerate(live):
            last = people[tr["frames"][-1]][tr["dets"][-1]]
            for j, p in enumerate(found):
                if not busy[j] and iou(last["box"], p["box"]) > LINK_IOU and look_distance(last["look"], p["look"]) < MAX_LOOK:
                    cost[i, j] = 1 - iou(last["box"], p["box"])
        kept, matched = [], set()
        if live and boxes:
            for i, j in zip(*linear_sum_assignment(cost)):
                if cost[i, j] < 1:
                    live[i]["frames"].append(f)
                    live[i]["dets"].append(j)
                    kept.append(live[i])
                    matched.add(j)
        done += [tr for tr in live if all(tr is not k for k in kept)]
        live = kept + [{"frames": [f], "dets": [j]} for j in range(len(found)) if j not in matched and not busy[j]]
    return done + live


def follows(times, a, b):
    gap = times[b["frames"][0]] - times[a["frames"][-1]]
    if not 0 < gap <= CHAIN_GAP:
        return False
    if look_distance(np.mean(a["looks"][-5:], 0), np.mean(b["looks"][:5], 0)) > MAX_LOOK:
        return False
    x, y = a["boxes"][-1], b["boxes"][0]
    return np.linalg.norm(center(x) - center(y)) / ((x[2] - x[0] + y[2] - y[0]) / 2) <= 0.25 + gap


def chain(times, pieces):
    while True:
        nxt = {id(a): [b for b in pieces if follows(times, a, b)] for a in pieces}
        prev = {}
        for a in pieces:
            for b in nxt[id(a)]:
                prev.setdefault(id(b), []).append(a)
        pair = next(((a, nxt[id(a)][0]) for a in pieces if len(nxt[id(a)]) == 1 and len(prev[id(nxt[id(a)][0])]) == 1), None)
        if pair is None:
            return pieces
        a, b = pair
        for key in ("frames", "dets", "boxes", "looks"):
            a[key] = a[key] + b[key]
        a["X"] = np.concatenate([a["X"], b["X"]])
        pieces = [p for p in pieces if p is not b]


def overlaps(a, b):
    return a["frames"][0] <= b["frames"][-1] and b["frames"][0] <= a["frames"][-1] and bool(set(a["frames"]) & set(b["frames"]))


def anchor(pieces, frames, count):
    def strength(f):
        active = sorted((len(tr["frames"]) for tr in pieces if tr["frames"][0] <= f <= tr["frames"][-1]), reverse=True)
        return np.log(active[:count]).sum() if len(active) >= count else -np.inf
    f = max(frames, key=strength)
    if not np.isfinite(strength(f)):
        return None
    group = sorted((tr for tr in pieces if tr["frames"][0] <= f <= tr["frames"][-1]), key=lambda tr: -len(tr["frames"]))[:count]
    return strength(f), sorted(group, key=lambda tr: center(tr["boxes"][tr["frames"].index(f)])[0])


class Classifier:
    def __init__(self, pieces, label, count):
        covered = {}
        for tr in pieces:
            if label.get(id(tr), OTHER) != OTHER:
                for f in tr["frames"]:
                    covered.setdefault(f, set()).add(label[id(tr)])
        full = {f for f, ids in covered.items() if len(ids) == count}
        others = [tr for tr in pieces if id(tr) not in label and sum(f in full for f in tr["frames"]) > len(tr["frames"]) / 2]
        xs, ys = [], []
        for tr in [tr for tr in pieces if id(tr) in label] + others:
            xs.append(tr["X"][::max(1, len(tr["X"]) // 60)])
            ys += [label.get(id(tr), OTHER)] * len(xs[-1])
        x = np.concatenate(xs)
        self.scaler = StandardScaler().fit(x)
        self.model = LogisticRegression(C=0.05, max_iter=3000).fit(self.scaler.transform(x), ys) if len(set(ys)) > 1 else None
        self.count = count

    def scores(self, tr):
        out = np.full(self.count + 1, -50.0)
        if self.model is None:
            out[0] = 0
            return out
        for c, v in zip(self.model.classes_, self.model.predict_log_proba(self.scaler.transform(tr["X"])).mean(0)):
            out[c] = v
        return out


def identities(times, people, count):
    pieces = tracklets(people)
    for tr in pieces:
        found = [people[f][j] for f, j in zip(tr["frames"], tr["dets"])]
        tr["boxes"] = [p["box"] for p in found]
        tr["looks"] = [p["look"] for p in found]
        tr["X"] = np.stack([np.concatenate([p["emb"], np.sqrt(p["look"].flatten()) * 10]) for p in found])
    pieces = chain(times, pieces)
    span = max(1, int(np.searchsorted(times, times[0] + ANCHOR_SPAN)))
    groups = sorted(filter(None, (anchor(pieces, range(s, min(s + span, len(times))), count) for s in range(0, len(times), span))), key=lambda g: -g[0])
    owner = [[None] * count for _ in times]
    if not groups:
        return owner
    label = {id(tr): d for d, tr in enumerate(groups[0][1])}
    for _, group in groups[1:]:
        clf = Classifier(pieces, label, count)
        cost = np.array([-clf.scores(tr)[:count] for tr in group])
        for i, tr in enumerate(group):
            if id(tr) in label:
                cost[i] = 1e6
                cost[i, label[id(tr)]] = -1e6
        for i, d in zip(*linear_sum_assignment(cost)):
            if id(group[i]) not in label and not any(label.get(id(tr)) == d and overlaps(group[i], tr) for tr in pieces):
                label[id(group[i])] = int(d)
    clf = Classifier(pieces, label, count)
    pending = [tr for tr in pieces if id(tr) not in label]
    scores = {id(tr): clf.scores(tr) for tr in pending}
    for tr in pending:
        for o in pieces:
            d = label.get(id(o), OTHER)
            if d != OTHER and overlaps(tr, o):
                scores[id(tr)][d] = -np.inf
    while pending:
        best = None
        for tr in pending:
            s = scores[id(tr)]
            order = np.argsort(-s)
            if order[0] == count or not np.isfinite(s[order[0]]):
                continue
            confidence = (s[order[0]] - max(s[order[1]], -10)) * np.sqrt(len(tr["frames"]))
            if best is None or confidence > best[0]:
                best = (confidence, tr, int(order[0]))
        if best is None:
            break
        _, chosen, d = best
        label[id(chosen)] = d
        pending = [tr for tr in pending if tr is not chosen]
        for tr in pending:
            if overlaps(tr, chosen):
                scores[id(tr)][d] = -np.inf
    for tr in pieces:
        d = label.get(id(tr), OTHER)
        if d != OTHER:
            for f, j in zip(tr["frames"], tr["dets"]):
                owner[f][d] = j
    return recover(times, people, owner, Classifier(pieces, label, count))


def recover(times, people, owner, clf):
    count = len(owner[0])
    known = [[f for f in range(len(times)) if owner[f][d] is not None] for d in range(count)]
    for f, row in enumerate(owner):
        missing = [d for d in range(count) if row[d] is None]
        free = [j for j in range(len(people[f])) if j not in row]
        if not missing or not free:
            continue
        guess = [expected(times, people, owner, known[d], d, f) for d in missing]
        scores = clf.model.predict_proba(clf.scaler.transform([np.concatenate([people[f][j]["emb"], np.sqrt(people[f][j]["look"].flatten()) * 10]) for j in free])) if clf.model else None
        cost = np.full((len(missing), len(free)), 9.0)
        for a, d in enumerate(missing):
            if guess[a] is None:
                continue
            for b, j in enumerate(free):
                overlap = iou(guess[a], people[f][j]["box"])
                p = scores[b][list(clf.model.classes_).index(d)] if scores is not None and d in clf.model.classes_ else 0
                if overlap > RECOVER_IOU and p > RECOVER_PROB:
                    cost[a, b] = (1 - overlap) + (1 - p)
        for a, b in zip(*linear_sum_assignment(cost)):
            if cost[a, b] < 9:
                row[missing[a]] = free[b]
    return owner


def expected(times, people, owner, seen, d, f):
    k = np.searchsorted(seen, f)
    before = seen[k - 1] if k > 0 else None
    after = seen[k] if k < len(seen) else None
    near = [g for g in (before, after) if g is not None and abs(times[g] - times[f]) <= RECOVER_GAP]
    if not near:
        return None
    if len(near) == 1:
        return people[near[0]][owner[near[0]][d]]["box"]
    w = (times[f] - times[before]) / (times[after] - times[before])
    return people[before][owner[before][d]]["box"] * (1 - w) + people[after][owner[after][d]]["box"] * w
