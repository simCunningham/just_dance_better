export type Point = [number, number, number]
export type Pose = Point[]
export type Song = { title: string; artist?: string; names: string[]; members?: { t: number; boxes: number[][]; names: string[] } }
export type Moves = { aspect: number; min_visibility: number; t: number[]; e: boolean[][]; dancers: number[]; d: Pose[][] }

declare const __LAN__: string

export const SONG = 'what_is_love_twice'
export const VIDEO = `/api/songs/${SONG}/video`
export const COLORS = ['#ff4f8b', '#35d0ff', '#ffd23f', '#6be675']
export const BONES = [[1, 2], [1, 3], [3, 5], [2, 4], [4, 6], [1, 7], [2, 8], [7, 8], [7, 9], [9, 11], [8, 10], [10, 12]]

const json = (path: string) => fetch(`/api/songs/${SONG}${path}`).then(r => (r.ok ? r.json() : Promise.reject(new Error(r.statusText))))

export const getSong = (): Promise<Song> => json('')
export const getMoves = (dancers: number[]): Promise<Moves> => json(`/moves?dancers=${dancers.join(',')}`)
export const joinUrl = (code: string) =>
  `${['localhost', '127.0.0.1'].includes(location.hostname) && __LAN__ ? `${location.protocol}//${__LAN__}:${location.port}` : location.origin}/?room=${code}`

export function drawPose(ctx: CanvasRenderingContext2D, pose: Pose, w: number, h: number, color: string, min = 0.5) {
  ctx.strokeStyle = color
  ctx.lineCap = 'round'
  ctx.beginPath()
  for (const [a, b] of BONES) {
    if (pose[a][2] < min || pose[b][2] < min) continue
    ctx.moveTo(pose[a][0] * w, pose[a][1] * h)
    ctx.lineTo(pose[b][0] * w, pose[b][1] * h)
  }
  ctx.stroke()
}
