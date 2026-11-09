import sys, pickle, numpy as np, cv2
from ultralytics import YOLO
video, run, out = sys.argv[1:4]; ts = [float(x) for x in sys.argv[4:]]
rows = pickle.load(open(run, 'rb')); times = np.array([r[0] for r in rows])
C = [(90,90,255),(58,176,255),(74,225,255),(125,227,91),(255,216,58),(255,140,90),(255,107,180),(213,107,255),(255,255,255)]
def iou(a, b):
    x0, y0 = max(a[0], b[0]), max(a[1], b[1]); x1, y1 = min(a[2], b[2]), min(a[3], b[3]); i = max(0, x1 - x0) * max(0, y1 - y0)
    return i / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i)
m = YOLO('models/yolo11m-seg.pt'); cap = cv2.VideoCapture(video); tiles = []
for t in ts:
    k = int(np.argmin(np.abs(times - t))); cap.set(cv2.CAP_PROP_POS_MSEC, rows[k][0] * 1000); _, f = cap.read()
    r = m.predict(f, classes=[0], conf=0.15, iou=0.75, imgsz=1280, device='mps', retina_masks=True, verbose=False)[0]
    bx = r.boxes.xyxy.cpu().numpy(); ms = r.masks.data.cpu().numpy() > 0.5; g = (f * 0.45).astype(np.uint8)
    for d, b in enumerate(rows[k][2]):
        if b is None: continue
        j = int(np.argmax([iou(x, b) for x in bx])); mk = ms[j]
        g[mk] = (f[mk] * 0.6 + np.array(C[d]) * 0.4).astype(np.uint8)
    for d, b in enumerate(rows[k][2]):
        if b is None: continue
        j = int(np.argmax([iou(x, b) for x in bx])); ys, xs = np.nonzero(ms[j])
        if len(xs): cv2.putText(g, str(d), (int(xs.mean()) - 15, int(ys.min()) + 40), 0, 1.8, (0, 0, 0), 10); cv2.putText(g, str(d), (int(xs.mean()) - 15, int(ys.min()) + 40), 0, 1.8, C[d], 4)
    cv2.putText(g, f'{rows[k][0]:.1f}s', (20, 60), 0, 2, (255, 255, 255), 4)
    ys = np.nonzero((f.sum(2) > 0).any(1))[0]
    tiles.append(cv2.resize(g, (960, 540)))
rowsimg = [np.hstack(tiles[i:i + 2] + [np.zeros_like(tiles[0])] * (2 - len(tiles[i:i + 2]))) for i in range(0, len(tiles), 2)]
cv2.imwrite(out, np.vstack(rowsimg))
