/**
 * WebSocket hook for real-time market data.
 *
 * Connects to /ws/live/{symbol}
 * Handles RawTrade and BookSnapshot events
 */

import { useEffect, useRef } from 'react'
import { useMarketDataStore } from '../store'

interface WebSocketMessage {
  type?: string
  eventType?: string
  symbol?: string
  trade_id?: string
  price_ticks?: number
  qty_steps?: number
  taker_side?: 'Buy' | 'Sell'
  exchange_timestamp_ms?: number
  message?: string
}

export function useWebSocket(symbol: string, enabled: boolean = true) {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<number>()
  const addTrade = useMarketDataStore((state) => state.addTrade)
  const setMarkPrice = useMarketDataStore((state) => state.setMarkPrice)

  useEffect(() => {
    // If disabled - close connection immediately
    if (!enabled) {
      console.log('[WebSocket] Disabled, closing connection')
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
      return
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const wsUrl = `${protocol}//${host}/ws/live/${symbol}`

    console.log('[WebSocket] Connecting to:', wsUrl)

    function connect() {
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        console.log('[WebSocket] Connected:', symbol)
      }

      ws.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data)

          if (message.type === 'connected') {
            console.log('[WebSocket] Server confirmed:', message.message)
            return
          }

          if (message.type === 'heartbeat' || message.type === 'pong') {
            return
          }

          if (message.type === 'trade' || message.eventType === 'RawTrade') {
            const tickSize = 0.1 // TODO: Get from instrument metadata
            addTrade(symbol, {
              time: message.exchange_timestamp_ms || Date.now(),
              price: (message.price_ticks || 0) * tickSize,
              volume: message.qty_steps || 0,
              side: message.taker_side || 'Buy',
            })
            return
          }

          if (message.type === 'mark_price') {
            setMarkPrice(symbol, message.price_ticks || 0)
            return
          }

          console.warn('[WebSocket] Unknown message type:', message.type)
        } catch (error) {
          console.error('[WebSocket] Failed to parse message:', error)
        }
      }

      ws.onerror = (error) => {
        console.error('[WebSocket] Error:', error)
      }

      ws.onclose = (event) => {
        console.log('[WebSocket] Closed:', event.code, event.reason)

        // Auto-reconnect only if enabled
        if (enabled) {
          reconnectTimeoutRef.current = window.setTimeout(() => {
            console.log('[WebSocket] Reconnecting...')
            connect()
          }, 3000)
        }
      }
    }

    connect()

    // Cleanup
    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [symbol, enabled, addTrade, setMarkPrice])

  return {
    connected: wsRef.current?.readyState === WebSocket.OPEN,
  }
}
