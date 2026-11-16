import { useCallback, useEffect, useRef, useState } from 'react'

export type Phase = 'lobby' | 'play' | 'results'
export type Player = { member: number; score: number; combo: number; last: number }
export type State = { type: 'state'; phase: Phase; t: number; playing: boolean }

const fresh = () => Math.random().toString(36).slice(2, 6).toUpperCase()

export const DEVICE = (sessionStorage.device ??= fresh() + fresh())
export const newCode = fresh

export function useRoom(code: string, onState: (state: State) => void) {
  const [others, setOthers] = useState<Record<string, Player[]>>({})
  const socket = useRef<WebSocket | null>(null)
  const handler = useRef(onState)
  handler.current = onState

  useEffect(() => {
    let closed = false
    const open = () => {
      const ws = (socket.current = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/rooms/${code}?device=${DEVICE}`))
      ws.onmessage = event => {
        const message = JSON.parse(event.data)
        if (message.type === 'state') handler.current(message)
        else setOthers(({ [message.device]: _, ...rest }) => (message.type === 'players' ? { ...rest, [message.device]: message.players } : rest))
      }
      ws.onclose = () => {
        if (!closed) setTimeout(open, 1000)
      }
    }
    open()
    return () => {
      closed = true
      socket.current?.close()
      setOthers({})
    }
  }, [code])

  const send = useCallback((message: object) => {
    if (socket.current?.readyState === WebSocket.OPEN) socket.current.send(JSON.stringify(message))
  }, [])

  return { others, send }
}
