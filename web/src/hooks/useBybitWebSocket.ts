/**
 * Direct Bybit WebSocket connection (Live mode only).
 *
 * Connects directly to Bybit's public WebSocket API for real-time data.
 * Used when isReplayMode = false.
 *
 * Bybit WebSocket API:
 * - wss://stream.bybit.com/v5/public/linear
 * - Topic: publicTrade.{symbol}
 * - Topic: kline.{interval}.{symbol}
 */

import { useEffect, useRef } from 'react'
import { useMarketDataStore } from '../store'
import { getInstrument } from '../api/instruments'
import { useQuery } from '@tanstack/react-query'

interface BybitTrade {
  T: number // timestamp (ms)
  s: string // symbol
  S: 'Buy' | 'Sell' // side
  v: string // volume
  p: string // price
  L: string // direction (PlusTick, ZeroPlusTick, MinusTick, ZeroMinusTick)
  i: string // trade ID
  BT: boolean // isBlockTrade
}

interface BybitKline {
  start: number // timestamp (ms)
  end: number
  interval: string
  open: string
  close: string
  high: string
  low: string
  volume: string
  turnover: string
  confirm: boolean // whether kline is closed
  timestamp: number
}

interface BybitMessage {
  topic: string
  type: string
  ts: number
  data: BybitTrade[] | BybitKline[]
}

export function useBybitWebSocket(symbol: string, enabled: boolean = true) {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<number>()
  const addTrade = useMarketDataStore((state) => state.addTrade)
  const pingIntervalRef = useRef<number>()

  // Fetch instrument metadata
  const { data: instrument } = useQuery({
    queryKey: ['instrument', symbol],
    queryFn: () => getInstrument(symbol),
    staleTime: Infinity,
  })

  useEffect(() => {
    if (!enabled || !instrument) {
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current)
      }
      return
    }

    const BYBIT_WS_URL = 'wss://stream.bybit.com/v5/public/linear'
    console.log('[BybitWebSocket] Connecting to Bybit:', BYBIT_WS_URL)

    function connect() {
      const ws = new WebSocket(BYBIT_WS_URL)
      wsRef.current = ws

      ws.onopen = () => {
        console.log('[BybitWebSocket] Connected to Bybit')

        // Subscribe to public trades
        ws.send(JSON.stringify({
          op: 'subscribe',
          args: [`publicTrade.${symbol}`],
        }))

        // Start ping every 20 seconds (Bybit requires ping to keep connection alive)
        pingIntervalRef.current = window.setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ op: 'ping' }))
          }
        }, 20000)
      }

      ws.onmessage = (event) => {
        try {
          const message: BybitMessage | { op?: string } = JSON.parse(event.data)

          // Handle pong
          if ('op' in message && message.op === 'pong') {
            return
          }

          // Handle subscription response
          if ('op' in message && message.op === 'subscribe') {
            console.log('[BybitWebSocket] Subscribed:', message)
            return
          }

          // Handle trade data
          if ('topic' in message && message.topic.startsWith('publicTrade.')) {
            const trades = message.data as BybitTrade[]

            trades.forEach((trade) => {
              addTrade(symbol, {
                time: trade.T, // Bybit sends ms timestamp
                price: parseFloat(trade.p),
                volume: parseFloat(trade.v),
                side: trade.S,
              })
            })
            return
          }

          console.warn('[BybitWebSocket] Unknown message:', message)
        } catch (error) {
          console.error('[BybitWebSocket] Failed to parse message:', error)
        }
      }

      ws.onerror = (error) => {
        console.error('[BybitWebSocket] Error:', error)
      }

      ws.onclose = (event) => {
        console.log('[BybitWebSocket] Closed:', event.code, event.reason)

        if (pingIntervalRef.current) {
          clearInterval(pingIntervalRef.current)
        }

        // Auto-reconnect only if enabled
        if (enabled) {
          reconnectTimeoutRef.current = window.setTimeout(() => {
            console.log('[BybitWebSocket] Reconnecting...')
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
      if (pingIntervalRef.current) {
        clearInterval(pingIntervalRef.current)
      }
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [symbol, enabled, instrument, addTrade])

  return {
    connected: wsRef.current?.readyState === WebSocket.OPEN,
  }
}
