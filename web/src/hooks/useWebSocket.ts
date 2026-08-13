/**
 * WebSocket hook for real-time market data.
 *
 * Подключается к /ws/live?symbol={symbol}
 * Обрабатывает RawTrade и BookSnapshot события
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
}

export function useWebSocket(symbol: string, enabled: boolean = true) {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<number>()
  const addTrade = useMarketDataStore((state) => state.addTrade)
  const setMarkPrice = useMarketDataStore((state) => state.setMarkPrice)

  useEffect(() => {
    if (!enabled || !symbol) {
      return
    }

    const connect = () => {
      // WebSocket URL - используем относительный путь для прокси
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const wsUrl = `${protocol}//${window.location.host}/ws/live?symbol=${symbol}`

      console.log('[WebSocket] Connecting to:', wsUrl)

      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        console.log('[WebSocket] Connected to', symbol)
      }

      ws.onmessage = (event) => {
        try {
          const msg: WebSocketMessage = JSON.parse(event.data)

          // Приветственное сообщение
          if (msg.type === 'connected') {
            console.log('[WebSocket] Connection confirmed:', msg)
            return
          }

          // RawTrade события
          if (msg.eventType === 'RawTrade' && msg.price_ticks && msg.qty_steps) {
            const trade = {
              time: msg.exchange_timestamp_ms || Date.now(),
              price: msg.price_ticks,
              volume: msg.qty_steps,
              side: msg.taker_side || 'Buy',
            }

            addTrade(symbol, trade)
            setMarkPrice(symbol, msg.price_ticks)
          }

          // BookSnapshot события (будущая поддержка)
          if (msg.eventType === 'BookSnapshot') {
            console.log('[WebSocket] Book snapshot received')
          }

        } catch (err) {
          console.error('[WebSocket] Parse error:', err)
        }
      }

      ws.onerror = (error) => {
        console.error('[WebSocket] Error:', error)
      }

      ws.onclose = (event) => {
        console.log('[WebSocket] Closed:', event.code, event.reason)

        // Auto-reconnect after 3 seconds
        if (enabled) {
          reconnectTimeoutRef.current = setTimeout(() => {
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
