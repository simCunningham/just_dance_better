import { useMemo } from 'react'
import { COLORS, type Song } from './api'
import type { Player } from './room'
import { RATINGS, type Tally } from './score'

type Props = { song: Song; names: string[]; members: number[]; tallies: Tally[]; others: Record<string, Player[]>; host: boolean; onHome: () => void; onRestart: () => void }

export default function Results({ song, names, members, tallies, others, host, onHome, onRestart }: Props) {
  const bests = useMemo(
    () =>
      members.map((member, i) => {
        const key = `best:${song.id}:${member}`
        const before = Number(localStorage[key] ?? 0)
        const score = tallies[i]?.score ?? 0
        if (score > before) localStorage[key] = score
        return { before, fresh: score > before }
      }),
    [],
  )
  const board = [
    ...members.map((member, i) => ({ member, color: COLORS[i], score: tallies[i]?.score ?? 0 })),
    ...Object.values(others).flat().map(p => ({ ...p, color: '#aaa' })),
  ].sort((a, b) => b.score - a.score)

  return (
    <main className="results">
      <nav>
        <button onClick={onHome}>{host ? 'Home' : 'Leave room'}</button>
        <span>{song.title}</span>
        {host ? <button className="primary" onClick={onRestart}>Restart</button> : <small>Waiting for the host</small>}
      </nav>
      <h1>Results</h1>
      <ol className="board">
        {board.map(row => (
          <li key={row.member}>
            <i style={{ background: row.color }} />
            {names[row.member]}
            <b>{row.score}</b>
          </li>
        ))}
      </ol>
      {tallies.map((tally, i) => (
        <section key={i} style={{ borderColor: COLORS[i] }}>
          <h2 style={{ color: COLORS[i] }}>
            {names[members[i]]} · {tally.score}
            <small>{bests[i].fresh ? 'New best!' : `Best ${bests[i].before}`}</small>
          </h2>
          <p>
            {RATINGS.map((rating, r) => (
              <span key={r} style={{ color: rating.color }}>{rating.name} {tally.marks.filter(mark => mark === r).length}</span>
            ))}
            <span>Longest combo {tally.best}</span>
          </p>
          <div className="strip">
            {Array.from(tally.marks, (mark, second) => (
              <i key={second} title={`${Math.floor(second / 60)}:${String(second % 60).padStart(2, '0')}`} style={{ background: RATINGS[mark]?.color ?? '#333' }} />
            ))}
          </div>
        </section>
      ))}
    </main>
  )
}
