import QRCode from 'qrcode'
import { useEffect, useState } from 'react'
import { COLORS, VIDEO, joinUrl, type Song } from './api'
import CamView from './CamView'
import { fullBody } from './pose'
import type { Player } from './room'

type Props = {
  song: Song
  members: number[]
  setMembers: (members: number[]) => void
  others: Record<string, Player[]>
  code: string
  host: boolean
  busy: boolean
  onStart: () => void
  onJoin: (code: string) => void
}

export default function Lobby({ song, members, setMembers, others, code, host, busy, onStart, onJoin }: Props) {
  const [active, setActive] = useState(0)
  const [size, setSize] = useState([16, 9])
  const [visible, setVisible] = useState(0)
  const [qr, setQr] = useState('')
  const [typed, setTyped] = useState('')
  const taken = Object.values(others).flat().map(p => p.member)
  const room = Math.min(4, 9 - taken.length)
  const ready = members.every(m => m >= 0)
  const url = joinUrl(code)

  useEffect(() => {
    QRCode.toDataURL(url, { margin: 1, width: 240 }).then(setQr)
  }, [url])

  const resize = (count: number) => {
    setMembers(Array.from({ length: count }, (_, i) => members[i] ?? -1))
    setActive(Math.min(active, count - 1))
  }

  const pick = (member: number) => {
    if (taken.includes(member) || members.includes(member)) return
    const next = members.map((m, i) => (i === active ? member : m))
    setMembers(next)
    const open = next.findIndex(m => m < 0)
    if (open >= 0) setActive(open)
  }

  const label = (member: number) => {
    const slot = members.indexOf(member)
    const mine = slot >= 0
    const gone = taken.includes(member)
    return { style: mine ? { borderColor: COLORS[slot], color: COLORS[slot] } : undefined, disabled: gone, text: song.names[member] + (mine ? ` · P${slot + 1}` : gone ? ' · taken' : '') }
  }

  return (
    <main className="lobby">
      <header>
        <h1>Just Dance Better</h1>
        <p>{song.title} · {song.artist}</p>
      </header>
      <section className="pick">
        <h2>Pick who you dance as</h2>
        <div className="slots">
          {members.map((member, i) => (
            <button key={i} className={i === active ? 'slot on' : 'slot'} style={{ borderColor: COLORS[i] }} onClick={() => setActive(i)}>
              <b style={{ color: COLORS[i] }}>Player {i + 1}</b>
              {member < 0 ? 'Pick a member' : song.names[member]}
            </button>
          ))}
          <div className="count">
            Players on this camera
            {[1, 2, 3, 4].map(n => (
              <button key={n} className={n === members.length ? 'on' : ''} disabled={n > room} onClick={() => resize(n)}>{n}</button>
            ))}
          </div>
        </div>
        {song.members && (
          <div className="frame" style={{ aspectRatio: `${size[0]} / ${size[1]}` }}>
            <video src={`${VIDEO}#t=${song.members.t}`} muted playsInline preload="metadata" onLoadedMetadata={e => setSize([e.currentTarget.videoWidth, e.currentTarget.videoHeight])} />
            {song.members.boxes.map(([x0, y0, x1, y1], i) => {
              const { text, ...rest } = label(song.names.indexOf(song.members!.names[i]))
              return (
                <button key={i} {...rest} onClick={() => pick(song.names.indexOf(song.members!.names[i]))} style={{ ...rest.style, left: `${(x0 / size[0]) * 100}%`, top: `${(y0 / size[1]) * 100}%`, width: `${((x1 - x0) / size[0]) * 100}%`, height: `${((y1 - y0) / size[1]) * 100}%` }}>
                  <span>{text}</span>
                </button>
              )
            })}
          </div>
        )}
        <div className="chips">
          {song.names.map((_, member) => {
            const { text, ...rest } = label(member)
            return <button key={member} {...rest} onClick={() => pick(member)}>{text}</button>
          })}
        </div>
      </section>
      <aside>
        <section>
          <h2>Camera check</h2>
          <CamView players={members.length} onFrame={poses => {
            const count = poses.filter(fullBody).length
            if (count !== visible) setVisible(count)
          }} />
          <p className={visible >= members.length ? 'ok' : 'warn'}>
            {visible} of {members.length} {members.length > 1 ? 'players' : 'player'} in full view. Stand back until your head and feet both show{members.length > 1 ? ', in player order from left to right' : ''}.
          </p>
        </section>
        <section className="room">
          <h2>Room {code}</h2>
          <p>Another laptop or phone can join with up to 4 more players each, 9 in total.</p>
          {qr && <img src={qr} alt="Join code" />}
          <a href={url}>{url}</a>
          {location.protocol === 'http:' && <p className="warn">Phones and other laptops need the secure link for their camera. Run npm run dev:lan and open the https address.</p>}
          {Object.values(others).map((players, i) => (
            <p key={i}>Device {i + 2}: {players.map(p => song.names[p.member]).join(', ') || 'picking'}</p>
          ))}
          <form onSubmit={e => {
            e.preventDefault()
            if (typed.trim()) onJoin(typed.trim().toUpperCase())
          }}>
            <input value={typed} onChange={e => setTyped(e.target.value)} placeholder="Room code" maxLength={8} />
            <button>Join another room</button>
          </form>
        </section>
        {host ? (
          <button className="start" disabled={!ready || busy} onClick={onStart}>{busy ? 'Loading…' : ready ? 'Start' : 'Pick members to start'}</button>
        ) : (
          <p className="start">{ready ? 'Waiting for the host to start' : 'Pick members to join in'}</p>
        )}
      </aside>
    </main>
  )
}
