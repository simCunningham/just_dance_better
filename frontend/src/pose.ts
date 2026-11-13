import { PoseLandmarker } from '@mediapipe/tasks-vision'
import wasmLoaderPath from '@mediapipe/tasks-vision/vision_wasm_internal.js?url'
import wasmBinaryPath from '@mediapipe/tasks-vision/vision_wasm_internal.wasm?url'
import type { Point, Pose } from './api'

const JOINTS = [0, 12, 11, 14, 13, 16, 15, 24, 23, 26, 25, 28, 27]

let camera: Promise<HTMLVideoElement> | undefined
let tracker: Promise<PoseLandmarker> | undefined

const create = (delegate: 'GPU' | 'CPU') =>
  PoseLandmarker.createFromOptions({ wasmLoaderPath, wasmBinaryPath }, { baseOptions: { modelAssetPath: '/api/model', delegate }, runningMode: 'VIDEO', numPoses: 4 })

export const getTracker = () => (tracker ??= create('GPU').catch(() => create('CPU')))

export const getCamera = () =>
  (camera ??= navigator.mediaDevices
    .getUserMedia({ video: { width: 1280, height: 720, facingMode: 'user' } })
    .then(async stream => {
      const video = Object.assign(document.createElement('video'), { srcObject: stream, muted: true, playsInline: true })
      await video.play()
      return video
    })
    .catch(error => {
      camera = undefined
      throw error
    }))

const centre = (pose: Pose) => (pose[1][0] + pose[2][0] + pose[7][0] + pose[8][0]) / 4

export const fullBody = (pose: Pose | null) => !!pose && [1, 2, 7, 8, 11, 12].every(i => pose[i][2] > 0.5)

export function track(landmarker: PoseLandmarker, video: HTMLVideoElement, slots: number[]) {
  const found = landmarker.detectForVideo(video, performance.now()).landmarks.map(l => JOINTS.map(j => [1 - l[j].x, l[j].y, l[j].visibility ?? 0] as Point))
  const pairs = found.flatMap((pose, i) => slots.map((x, j) => [Math.abs(centre(pose) - x), i, j])).sort((a, b) => a[0] - b[0])
  const poses: (Pose | null)[] = slots.map(() => null)
  const used = new Set<number>()
  for (const [, i, j] of pairs) {
    if (used.has(i) || poses[j]) continue
    used.add(i)
    poses[j] = found[i]
    slots[j] = centre(found[i])
  }
  return poses
}
