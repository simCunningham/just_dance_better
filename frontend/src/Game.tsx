import { useEffect, useMemo, useRef, useState, type RefObject } from 'react'
import { COLORS, VIDEO, drawPose, type Moves, type Pose } from './api'
import CamView from './CamView'
import type { Player } from './room'
import { RATINGS, Scorer, frameAt, type Tally } from './score'

type Props = {
  moves: Moves
  members: number[]
  names: string[]
  host: boolean
  clock: RefObject<{ t: number; playing: boolean; at: number }>
  others: Record<string, Player[]>
  onTallies: (tallies: Tally[]) => void
  onEnd: () => void
}

export default function Game({ moves, members, names, host, clock, others, onTallies, onEnd }: Props) {
  const video = useRef<HTMLVideoElement>(null)
  const overlay = useRef<HTMLCanvasElement>(null)
  const scorers = useMemo(() => members.map(member => new Scorer(moves, moves.dancers.indexOf(member))), [moves, members])
  const [count, setCount] = useState(host ? 3 : 0)
  const [muted, setMuted] = useState(!host)
  const [paused, setPaused] = useState(true)
  const [tallies, setTallies] = useState(() => scorers.map(s => ({ ...s.tally })))

  useEffect(() => {
    if (!host) return
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
    ctx.clearRect(0, 0, w, h)
    ctx.lineWidth = h / 150
    ctx.font = `600 ${h / 36}px system-ui`
    ctx.textAlign = 'center'
    const at = frameAt(moves.t, v.currentTime)
    members.forEach((member, i) => {
      const k = moves.dancers.indexOf(member)
      const pose = moves.d[k][at]
      ctx.globalAlpha = moves.e[k][at] ? 0.3 : 0.85
      drawPose(ctx, pose, w, h, COLORS[i], moves.min_visibility)
      ctx.fillStyle = COLORS[i]
      ctx.fillText(names[member], pose[0][0] * w, pose[0][1] * h - h / 22)
    })
  }

  const board = [
    ...members.map((member, i) => ({ member, color: COLORS[i], ...tallies[i] })),
    ...Object.values(others).flat().map(p => ({ ...p, color: '#aaa' })),
  ].sort((a, b) => b.score - a.score)

  return (
    <main className="game">
      <div className="stage" style={{ '--aspect': moves.aspect } as React.CSSProperties}>
        <video ref={video} src={VIDEO} muted={muted} playsInline preload="auto" onEnded={() => host && onEnd()} />
        <canvas ref={overlay} />
        {(count > 0 || (!host && paused)) && <div className="count">{host ? count : 'Get ready'}</div>}
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
        {host ? <button onClick={onEnd}>End song</button> : <button onClick={() => setMuted(!muted)}>{muted ? 'Turn sound on' : 'Turn sound off'}</button>}
      </div>
    </main>
  )
}
