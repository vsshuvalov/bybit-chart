/**
 * WebSocket hook for real-time market data.
 *
 * Connects to /ws/live/{symbol}
 * Handles RawTrade and BookSnapshot events
 */

import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useMarketDataStore } from '../store'
import { getInstrument } from '../api/instruments'

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

  // Fetch instrument metadata for tick_size
  const { data: instrument } = useQuery({
    queryKey: ['instrument', symbol],
    queryFn: () => getInstrument(symbol),
    staleTime: Infinity, // Instrument specs never change
  })

  useEffect(() => {
    // If disabled or no instrument data yet - close connection
    if (!enabled || !instrument) {
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
            if (!instrument) return // Should not happen (checked in useEffect guard)

            addTrade(symbol, {
              time: message.exchange_timestamp_ms || Date.now(),
              price: (message.price_ticks || 0) * instrument.tick_size,
              volume: (message.qty_steps || 0) * instrument.qty_step,
              side: message.taker_side || 'Buy',
            })
            return
          }

          if (message.type === 'mark_price') {
            if (!instrument) return // Should not happen (checked in useEffect guard)

            const markPrice = (message.price_ticks || 0) * instrument.tick_size
            setMarkPrice(symbol, markPrice)
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
  }, [symbol, enabled, instrument, addTrade, setMarkPrice])

  return {
    connected: wsRef.current?.readyState === WebSocket.OPEN,
  }
}
