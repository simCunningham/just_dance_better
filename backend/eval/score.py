import sys, json, pickle, os
import cv2, numpy as np

STEP = 1.5
BONES = ((11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (11, 23), (12, 24), (23, 24), (23, 25), (25, 27), (24, 26), (26, 28))


def iou(a, b):
    x0, y0 = max(a[0], b[0]), max(a[1], b[1]); x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    i = max(0, x1 - x0) * max(0, y1 - y0)
    return i / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i)


def samples(rows):
    return [min(range(len(rows)), key=lambda j: abs(rows[j][0] - t)) for t in np.arange(0.5, rows[-1][0], STEP)]


def load(path):
    return json.load(open(path)) if os.path.exists(path) else {"hidden": [], "boxes": []}


def init(run, out, wrong, hidden):
    rows = pickle.load(open(run, 'rb')); lab = {"hidden": hidden, "boxes": []}
    for k in samples(rows):
        t = round(rows[k][0], 2)
        for d, b in enumerate(rows[k][2]):
            if b is not None:
                lab["boxes"].append([t, d, [float(v) for v in b], not any(abs(t - w[0]) < 0.3 and d == w[1] for w in wrong)])
    json.dump(lab, open(out, 'w'))


def judge(lab, t, d, b):
    for lt, ld, lb, ok in lab["boxes"]:
        if abs(lt - t) < 0.3 and ld == d and iou(lb, b) > 0.7:
            return ok
    return None


def score(run, labf, verbose=True):
    rows = pickle.load(open(run, 'rb')); lab = load(labf)
    good = bad = miss = hidden = 0; unknown = []
    for k in samples(rows):
        t = round(rows[k][0], 2)
        for d, b in enumerate(rows[k][2]):
            if any(abs(t - h[0]) < 0.3 and d == h[1] for h in lab["hidden"]):
                hidden += 1
                continue
            if b is None:
                miss += 1
                continue
            v = judge(lab, t, d, b)
            if v is None: unknown.append((t, d))
            elif v: good += 1
            else: bad += 1
    total = good + bad + miss + len(unknown)
    if verbose:
        print(f"{os.path.basename(run)}: {good}/{total} = {100 * good / total:.1f}%  wrong {bad}  missing {miss}  hidden {hidden}  unverified {len(unknown)}")
    return good, total, unknown


def verify_sheet(video, run, labf, out):
    rows = pickle.load(open(run, 'rb')); _, _, unknown = score(run, labf, False)
    cap = cv2.VideoCapture(video); W, H = 130, 260; cols = 10
    img = np.zeros(((len(unknown) + cols - 1) // cols * (H + 24) + 1, cols * (W + 4), 3), np.uint8)
    times = [r[0] for r in rows]
    for i, (t, d) in enumerate(unknown):
        k = int(np.argmin(np.abs(np.array(times) - t))); cap.set(cv2.CAP_PROP_POS_MSEC, rows[k][0] * 1000); _, f = cap.read()
        b = rows[k][2][d]; pose = rows[k][3][d]; FH, FW = f.shape[:2]
        if pose is not None:
            for a, z in BONES:
                cv2.line(f, (int(pose[a][0] * FW), int(pose[a][1] * FH)), (int(pose[z][0] * FW), int(pose[z][1] * FH)), (0, 255, 0), 4)
        x0, y0, x1, y1 = [int(v) for v in b]
        r, c = divmod(i, cols)
        img[r * (H + 24) + 22:r * (H + 24) + 22 + H, c * (W + 4):c * (W + 4) + W] = cv2.resize(f[max(0, y0):y1, max(0, x0):x1], (W, H))
        cv2.putText(img, f'#{i} id{d} {t:.1f}', (c * (W + 4) + 2, r * (H + 24) + 16), 0, 0.45, (0, 255, 255), 1)
    cv2.imwrite(out, img)
    return unknown


def add(run, labf, verdicts):
    rows = pickle.load(open(run, 'rb')); lab = load(labf); _, _, unknown = score(run, labf, False)
    times = [r[0] for r in rows]
    for i, (t, d) in enumerate(unknown):
        k = int(np.argmin(np.abs(np.array(times) - t)))
        lab["boxes"].append([t, d, [float(v) for v in rows[k][2][d]], i not in verdicts["wrong"]])
    lab["hidden"] += verdicts.get("hidden", [])
    json.dump(lab, open(labf, 'w'))


if __name__ == '__main__':
    m = sys.argv[1]
    if m == 'init': init(sys.argv[2], sys.argv[3], json.loads(sys.argv[4]), json.loads(sys.argv[5]))
    elif m == 'score':
        G = T = 0
        for run, labf in zip(sys.argv[2::2], sys.argv[3::2]):
            g, t, _ = score(run, labf); G += g; T += t
        print(f'TOTAL {G}/{T} = {100 * G / T:.1f}%')
    elif m == 'verify': print(len(verify_sheet(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])), 'to check')
    elif m == 'add': add(sys.argv[2], sys.argv[3], json.loads(sys.argv[4]))
