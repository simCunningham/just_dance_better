import { useEffect, useMemo, useRef, useState, type RefObject } from 'react'
import { COLORS, drawPose, type Moves, type Pose } from './api'
import CamView from './CamView'
import type { Player } from './room'
import { RATINGS, Scorer, frameAt, type Tally } from './score'

type Props = {
  video: string
  crop: number[]
  moves: Moves
  members: number[]
  names: string[]
  host: boolean
  clock: RefObject<Clock>
  others: Record<string, Player[]>
  onTallies: (tallies: Tally[]) => void
  onEnd: () => void
  onRestart: () => void
}

export type Clock = { t: number; playing: boolean; at: number; count: number }

export const COUNTDOWN = 5

export default function Game({ video: src, crop, moves, members, names, host, clock, others, onTallies, onEnd, onRestart }: Props) {
  const video = useRef<HTMLVideoElement>(null)
  const overlay = useRef<HTMLCanvasElement>(null)
  const scorers = useMemo(() => members.map(member => new Scorer(moves, moves.dancers.indexOf(member))), [moves, members])
  const [count, setCount] = useState(host ? COUNTDOWN : 0)
  const [muted, setMuted] = useState(!host)
  const [paused, setPaused] = useState(true)
  const [tallies, setTallies] = useState(() => scorers.map(s => ({ ...s.tally })))

  useEffect(() => {
    if (!host) return
    clock.current.count = count
    if (!count) {
      video.current?.play()
      return
    }
    const id = setTimeout(() => setCount(count - 1), 1000)
    return () => clearTimeout(id)
  }, [count, host])

  useEffect(() => {
    const share = () => {
      const next = scorers.map(s => ({ ...s.tally }))
      setTallies(next)
      onTallies(next)
      setPaused(!!video.current?.paused)
    }
    const id = setInterval(share, 250)
    return () => {
      clearInterval(id)
      scorers.forEach(s => s.close())
      share()
    }
  }, [scorers])

  const frame = (poses: (Pose | null)[], aspect: number) => {
    const v = video.current
    const c = overlay.current
    if (!v || !c) return
    if (host) Object.assign(clock.current, { t: v.currentTime, playing: !v.paused })
    else {
      const { t, playing, at } = clock.current
      const want = t + (playing ? (performance.now() - at) / 1000 : 0)
      if (playing && v.paused) v.play().catch(() => {})
      if (!playing && !v.paused) v.pause()
      if (Math.abs(v.currentTime - want) > 0.35) v.currentTime = want
    }
    if (!v.paused) scorers.forEach((s, i) => s.add(v.currentTime, poses[i], aspect))
    const w = c.clientWidth * devicePixelRatio
    const h = c.clientHeight * devicePixelRatio
    if (c.width !== w || c.height !== h) Object.assign(c, { width: w, height: h })
    const ctx = c.getContext('2d')!
    ctx.setTransform(1, 0, 0, 1, 0, 0)
    ctx.clearRect(0, 0, w, h)
    const [x0, y0, x1, y1] = crop
    const fw = w / (x1 - x0)
    const fh = h / (y1 - y0)
    ctx.setTransform(1, 0, 0, 1, -x0 * fw, -y0 * fh)
    ctx.lineWidth = h / 150
    ctx.font = `600 ${h / 36}px system-ui`
    ctx.textAlign = 'center'
    const at = frameAt(moves.t, v.currentTime)
    members.forEach((member, i) => {
      const k = moves.dancers.indexOf(member)
      const pose = moves.d[k][at]
      ctx.globalAlpha = moves.e[k][at] ? 0.3 : 0.85
      drawPose(ctx, pose, fw, fh, COLORS[i], moves.min_visibility)
      ctx.fillStyle = COLORS[i]
      ctx.fillText(names[member], pose[0][0] * fw, pose[0][1] * fh - h / 22)
    })
  }

  const toggle = () => {
    const v = video.current!
    if (v.paused) setCount(COUNTDOWN)
    else {
      v.pause()
      setPaused(true)
    }
  }

  const shown = host ? count : clock.current.count
  const [x0, y0, x1, y1] = crop

  const board = [
    ...members.map((member, i) => ({ member, color: COLORS[i], ...tallies[i] })),
    ...Object.values(others).flat().map(p => ({ ...p, color: '#aaa' })),
  ].sort((a, b) => b.score - a.score)

  return (
    <main className="game">
      <div className="stage" style={{ '--aspect': (moves.aspect * (x1 - x0)) / (y1 - y0) } as React.CSSProperties}>
        <video ref={video} src={src} style={{ left: `${(-x0 / (x1 - x0)) * 100}%`, top: `${(-y0 / (y1 - y0)) * 100}%`, width: `${100 / (x1 - x0)}%`, height: `${100 / (y1 - y0)}%` }} muted={muted} playsInline preload="auto" onEnded={() => host && onEnd()} />
        <canvas ref={overlay} />
        {(shown > 0 || paused) && <div className="count">{shown > 0 ? <b key={shown}>{shown}</b> : video.current?.currentTime ? 'Paused' : 'Get ready'}</div>}
      </div>
      <ol className="board">
        {board.map(row => (
          <li key={row.member}>
            <i style={{ background: row.color }} />
            {names[row.member]}
            <b>{row.score}</b>
            {row.combo > 1 && <small>×{row.combo}</small>}
          </li>
        ))}
      </ol>
      <div className="me">
        <CamView players={members.length} onFrame={frame} />
        <div className="ratings">
          {tallies.map((tally, i) => (
            <span key={i} style={{ borderColor: COLORS[i] }}>
              {names[members[i]]}
              <b key={tally.marks.length} style={{ color: RATINGS[tally.last]?.color }}>{RATINGS[tally.last]?.name ?? '…'}</b>
            </span>
          ))}
        </div>
        {host ? (
          <div className="controls">
            <button disabled={count > 0} onClick={toggle}>{paused ? 'Resume' : 'Pause'}</button>
            <button disabled={count > 0} onClick={onRestart}>Restart</button>
            <button onClick={onEnd}>End song</button>
          </div>
        ) : (
          <button onClick={() => setMuted(!muted)}>{muted ? 'Turn sound on' : 'Turn sound off'}</button>
        )}
      </div>
    </main>
  )
}
