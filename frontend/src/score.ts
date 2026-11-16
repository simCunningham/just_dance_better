import type { Moves, Pose } from './api'

const LIMBS = [[1, 3, 2], [3, 5, 2], [2, 4, 2], [4, 6, 2], [7, 9, 1], [9, 11, 1], [8, 10, 1], [10, 12, 1]]

export const RATINGS = [
  { name: 'Perfect', min: 0.75, points: 100, color: '#6be675' },
  { name: 'Good', min: 0.6, points: 60, color: '#35d0ff' },
  { name: 'OK', min: 0.45, points: 30, color: '#ffd23f' },
  { name: 'Miss', min: 0, points: 0, color: '#ff5a5a' },
]

export type Tally = { score: number; combo: number; best: number; last: number; marks: number[] }

export const newTally = (): Tally => ({ score: 0, combo: 0, best: 0, last: -1, marks: [] })

export function frameAt(times: number[], t: number) {
  let lo = 0
  let hi = times.length - 1
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1
    if (times[mid] <= t) lo = mid
    else hi = mid - 1
  }
  return lo
}

export function similarity(target: Pose, player: Pose, targetAspect: number, playerAspect: number, min: number) {
  let sum = 0
  let total = 0
  for (const [a, b, weight] of LIMBS) {
    if (target[a][2] < min || target[b][2] < min) continue
    total += weight
    if (player[a][2] < 0.5 || player[b][2] < 0.5) continue
    const tx = (target[b][0] - target[a][0]) * targetAspect
    const ty = target[b][1] - target[a][1]
    const px = (player[b][0] - player[a][0]) * playerAspect
    const py = player[b][1] - player[a][1]
    const cos = (tx * px + ty * py) / (Math.hypot(tx, ty) * Math.hypot(px, py) || 1)
    sum += weight * Math.max(0, 1 - Math.acos(Math.max(-1, Math.min(1, cos))) / (Math.PI / 2))
  }
  return total ? sum / total : null
}

export class Scorer {
  tally = newTally()
  private second = -1
  private sum = 0
  private count = 0

  constructor(private moves: Moves, private index: number) {}

  add(t: number, pose: Pose | null, aspect: number) {
    const second = Math.floor(t)
    if (second !== this.second) {
      this.close()
      this.second = second
    }
    const { t: times, e, d, aspect: targetAspect, min_visibility } = this.moves
    if (e[this.index][frameAt(times, t)]) return
    let best: number | null = null
    for (let i = frameAt(times, t - 0.4), end = frameAt(times, t + 0.1); i <= end; i += 2) {
      if (e[this.index][i]) continue
      const s = pose ? similarity(d[this.index][i], pose, targetAspect, aspect, min_visibility) : 0
      if (s !== null && (best === null || s > best)) best = s
    }
    if (best === null) return
    this.sum += best
    this.count++
  }

  close() {
    const { tally } = this
    if (this.second >= 0) {
      const mean = this.sum / this.count
      const rating = this.count < 5 ? -1 : RATINGS.findIndex(r => mean >= r.min)
      tally.marks[this.second] = rating
      if (rating >= 0) {
        tally.last = rating
        tally.combo = RATINGS[rating].points ? tally.combo + 1 : 0
        tally.best = Math.max(tally.best, tally.combo)
        tally.score += RATINGS[rating].points + (RATINGS[rating].points ? Math.min(tally.combo, 20) : 0)
      }
    }
    this.second = -1
    this.sum = this.count = 0
  }
}
