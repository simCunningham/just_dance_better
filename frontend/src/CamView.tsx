import type { PoseLandmarker } from '@mediapipe/tasks-vision'
import { useEffect, useRef, useState } from 'react'
import { COLORS, drawPose, type Pose } from './api'
import { getCamera, getTracker, track } from './pose'

type Props = { players: number; onFrame?: (poses: (Pose | null)[], aspect: number) => void }

export default function CamView({ players, onFrame }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const frame = useRef(onFrame)
  const [status, setStatus] = useState('Starting camera…')
  frame.current = onFrame

  useEffect(() => {
    let raf = 0
    let last = -1
    let video: HTMLVideoElement | undefined
    let tracker: PoseLandmarker | undefined
    let poses: (Pose | null)[] = Array(players).fill(null)
    const slots = Array.from({ length: players }, (_, i) => (i + 0.5) / players)
    getCamera()
      .then(v => {
        video = v
        setStatus('Loading pose tracking…')
        return getTracker()
      })
      .then(t => {
        tracker = t
        setStatus('')
      })
      .catch(error => setStatus(video ? `Pose tracking failed: ${error.message}` : 'Camera unavailable. Allow camera access and reload.'))
    const tick = () => {
      raf = requestAnimationFrame(tick)
      const c = canvas.current
      if (c && video) {
        if (tracker && video.currentTime !== last) {
          last = video.currentTime
          poses = track(tracker, video, slots)
        }
        if (c.width !== video.videoWidth) Object.assign(c, { width: video.videoWidth, height: video.videoHeight })
        const ctx = c.getContext('2d')!
        ctx.save()
        ctx.scale(-1, 1)
        ctx.drawImage(video, -c.width, 0)
        ctx.restore()
        ctx.lineWidth = c.width / 100
        poses.forEach((pose, i) => pose && drawPose(ctx, pose, c.width, c.height, COLORS[i]))
      }
      frame.current?.(poses, video ? video.videoWidth / video.videoHeight : 1)
    }
    tick()
    return () => cancelAnimationFrame(raf)
  }, [players])

  return (
    <div className="cam">
      <canvas ref={canvas} />
      {status && <p>{status}</p>}
    </div>
  )
}
