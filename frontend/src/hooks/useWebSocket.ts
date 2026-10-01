// WebSocket hook — connects to /ws/kpi-stream and pushes typed messages
import { useEffect, useRef, useCallback, useState } from 'react'

export type WSMessageType =
  | 'connected'
  | 'state_snapshot'
  | 'drift_alert'
  | 'intent_compiled'
  | 'envelope_issued'
  | 'envelope_revoked'
  | 'heartbeat'
  | 'ack'

export interface WSMessage {
  type: WSMessageType
  payload: Record<string, unknown>
  ts: number
}

export type WSStatus = 'connecting' | 'open' | 'closed' | 'error'

interface UseWebSocketOptions {
  url: string
  onMessage?: (msg: WSMessage) => void
  reconnectDelay?: number
}

export function useWebSocket({ url, onMessage, reconnectDelay = 3000 }: UseWebSocketOptions) {
  const [status, setStatus] = useState<WSStatus>('connecting')
  const wsRef = useRef<WebSocket | null>(null)
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)

  const connect = useCallback(() => {
    if (!mountedRef.current) return
    setStatus('connecting')

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      if (mountedRef.current) setStatus('open')
    }

    ws.onmessage = (event) => {
      if (!mountedRef.current) return
      try {
        const msg: WSMessage = JSON.parse(event.data)
        onMessage?.(msg)
      } catch { /* ignore malformed */ }
    }

    ws.onerror = () => {
      if (mountedRef.current) setStatus('error')
    }

    ws.onclose = () => {
      if (!mountedRef.current) return
      setStatus('closed')
      retryRef.current = setTimeout(connect, reconnectDelay)
    }
  }, [url, onMessage, reconnectDelay])

  useEffect(() => {
    mountedRef.current = true
    connect()
    return () => {
      mountedRef.current = false
      wsRef.current?.close()
      if (retryRef.current) clearTimeout(retryRef.current)
    }
  }, [connect])

  return { status }
}
