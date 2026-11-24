import { useEffect, useRef, useState } from 'react'
import { cropOf, getMoves, getSongs, videoUrl, type Moves, type Song } from './api'
import Game, { type Clock } from './Game'
import Lobby from './Lobby'
import Results from './Results'
import { DEVICE, newCode, useRoom, type Phase } from './room'
import type { Tally } from './score'

const joined = new URLSearchParams(location.search).get('room')?.toUpperCase()

export default function App() {
  const [code, setCode] = useState(joined || newCode)
  const [host, setHost] = useState(!joined || location.hash === '#host')
  const [phase, setPhase] = useState<Phase>('lobby')
  const [songs, setSongs] = useState<Song[]>()
  const [songId, setSongId] = useState('')
  const [error, setError] = useState('')
  const [members, setMembers] = useState([-1])
  const [moves, setMoves] = useState<Moves>()
  const [busy, setBusy] = useState(false)
  const [tallies, setTallies] = useState<Tally[]>([])
  const [round, setRound] = useState(0)
  const clock = useRef<Clock>({ t: 0, playing: false, at: 0, count: 0 })
  const { others, send } = useRoom(code, state => {
    if (host) return
    clock.current = { t: state.t, playing: state.playing, at: performance.now(), count: state.count ?? 0 }
    setRound(state.round ?? 0)
    if (state.song && state.song !== latest.current.songId) pickSong(state.song)
    setPhase(state.phase)
  })
  const song = songs?.find(s => s.id === songId)
  const ready = members.every(m => m >= 0)
  const latest = useRef({ members, tallies, phase, host, songId, round })
  latest.current = { members, tallies, phase, host, songId, round }

  const pickSong = (id: string) => {
    setSongId(id)
    setMembers(members => members.map(() => -1))
  }

  useEffect(() => {
    getSongs().then(list => {
      setSongs(list)
      setSongId(id => id || list[0]?.id || '')
    }, () => setError('Could not reach the game server. Start the backend and reload.'))
  }, [])

  useEffect(() => {
    history.replaceState(null, '', `?room=${code}${host ? '#host' : ''}`)
  }, [code, host])

  useEffect(() => {
    const id = setInterval(() => {
      const { members, tallies, phase, host, songId, round } = latest.current
      const players = members.map((member, i) => ({ member, score: 0, combo: 0, last: -1, ...(phase === 'lobby' ? {} : tallies[i]), marks: undefined })).filter(p => p.member >= 0)
      send({ type: 'players', device: DEVICE, players })
      if (host) send({ type: 'state', phase, song: songId, t: clock.current.t, playing: clock.current.playing, count: clock.current.count, round })
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
    return getMoves(songId, members)
      .then(setMoves, () => setError('Could not load the moves.'))
      .finally(() => setBusy(false))
  }

  if (error) return <p className="notice">{error}</p>
  if (!songs) return <p className="notice">Loading…</p>
  if (!song) return <p className="notice">No songs are ready yet. Process a song in the backend and reload.</p>
  const reset = () => {
    clock.current = { t: 0, playing: false, at: 0, count: 0 }
    setTallies([])
  }
  const restart = () => {
    reset()
    setRound(r => r + 1)
    setPhase('play')
  }
  const home = () => {
    reset()
    if (!host) {
      setCode(newCode())
      setHost(true)
    }
    setPhase('lobby')
  }

  if (phase === 'play' && moves)
    return <Game key={`${song.id}:${moves.t.length}:${members.join()}:${round}`} video={videoUrl(song.id)} crop={cropOf(song)} start={song.start ?? 0} moves={moves} members={members} names={song.names} host={host} clock={clock} others={others} onTallies={setTallies} onEnd={() => setPhase('results')} onRestart={restart} />
  if (phase === 'results')
    return <Results key={round} song={song} names={song.names} members={moves ? members : []} tallies={tallies} others={others} host={host} onHome={home} onRestart={restart} />
  return (
    <Lobby song={song} songs={songs} onSong={pickSong} members={members} setMembers={setMembers} others={others} code={code} host={host} busy={busy} onStart={() => load().then(() => setPhase('play'))} onJoin={next => {
      setCode(next)
      setHost(false)
    }} />
  )
}
