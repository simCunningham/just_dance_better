import { useEffect, useRef, useState } from 'react'
import { getMoves, getSong, type Moves, type Song } from './api'
import Game from './Game'
import Lobby from './Lobby'
import Results from './Results'
import { DEVICE, newCode, useRoom, type Phase } from './room'
import type { Tally } from './score'

const joined = new URLSearchParams(location.search).get('room')?.toUpperCase()

export default function App() {
  const [code, setCode] = useState(joined || newCode)
  const [host, setHost] = useState(!joined || location.hash === '#host')
  const [phase, setPhase] = useState<Phase>('lobby')
  const [song, setSong] = useState<Song>()
  const [error, setError] = useState('')
  const [members, setMembers] = useState([-1])
  const [moves, setMoves] = useState<Moves>()
  const [busy, setBusy] = useState(false)
  const [tallies, setTallies] = useState<Tally[]>([])
  const clock = useRef({ t: 0, playing: false, at: 0 })
  const { others, send } = useRoom(code, state => {
    if (host) return
    clock.current = { t: state.t, playing: state.playing, at: performance.now() }
    setPhase(state.phase)
  })
  const ready = members.every(m => m >= 0)
  const latest = useRef({ members, tallies, phase, host })
  latest.current = { members, tallies, phase, host }

  useEffect(() => {
    getSong().then(setSong, () => setError('Could not reach the game server. Start the backend and reload.'))
  }, [])

  useEffect(() => {
    history.replaceState(null, '', `?room=${code}${host ? '#host' : ''}`)
  }, [code, host])

  useEffect(() => {
    const id = setInterval(() => {
      const { members, tallies, phase, host } = latest.current
      const players = members.map((member, i) => ({ member, score: 0, combo: 0, last: -1, ...(phase === 'lobby' ? {} : tallies[i]), marks: undefined })).filter(p => p.member >= 0)
      send({ type: 'players', device: DEVICE, players })
      if (host) send({ type: 'state', phase, t: clock.current.t, playing: clock.current.playing })
    }, 500)
    return () => clearInterval(id)
  }, [send])

  useEffect(() => {
    if (phase === 'lobby') setMoves(undefined)
    else if (phase === 'play' && !host && ready && !moves && !busy) load()
  }, [phase, host, ready, moves, busy])

  const load = () => {
    setBusy(true)
    setTallies([])
    return getMoves(members)
      .then(setMoves, () => setError('Could not load the moves.'))
      .finally(() => setBusy(false))
  }

  if (error) return <p className="notice">{error}</p>
  if (!song) return <p className="notice">Loading…</p>
  if (phase === 'play' && moves)
    return <Game key={moves.t.length + members.join()} moves={moves} members={members} names={song.names} host={host} clock={clock} others={others} onTallies={setTallies} onEnd={() => setPhase('results')} />
  if (phase === 'results')
    return <Results names={song.names} members={moves ? members : []} tallies={tallies} others={others} host={host} onAgain={() => {
      clock.current = { t: 0, playing: false, at: 0 }
      setPhase('lobby')
    }} />
  return (
    <Lobby song={song} members={members} setMembers={setMembers} others={others} code={code} host={host} busy={busy} onStart={() => load().then(() => setPhase('play'))} onJoin={next => {
      setCode(next)
      setHost(false)
    }} />
  )
}
