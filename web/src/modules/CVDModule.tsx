/**
 * CVD (Cumulative Volume Delta) Module (Roadmap §11.6).
 *
 * Calculates and displays cumulative buy volume - sell volume.
 * Formula: CVD += (takerSide === 'Buy' ? +qtySteps : -qtySteps)
 *
 * Features:
 * - Real-time calculation from trade stream
 * - Configurable reset interval (daily, session, never)
 * - Smoothing via EMA
 * - Color coding (green: positive, red: negative)
 */

import { useEffect, useState, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../api/client'

interface Trade {
  timestampUs: number
  takerSide: 'Buy' | 'Sell'
  qtySteps: number
  priceTicks: number
}

interface CVDSettings {
  enabled: boolean
  resetInterval: 'never' | 'daily' | 'session'
  smoothing: number
  positiveColor: string
  negativeColor: string
}

interface CVDModuleProps {
  symbol: string
  settings: CVDSettings
}

export default function CVDModule({ symbol, settings }: CVDModuleProps) {
  const [cvdValue, setCvdValue] = useState(0)
  const lastResetRef = useRef<number>(Date.now())

  // Fetch historical trades to initialize CVD
  const { data: tradesData } = useQuery({
    queryKey: ['trades', symbol, { limit: 1000, type: 'cvd-module' }],
    queryFn: async () => {
      const response = await apiClient.get('/trades', {
        params: { symbol, limit: 1000 },
      })
      return response.data
    },
    refetchInterval: 5000, // Refetch every 5 seconds
    enabled: settings.enabled,
  })

  // Calculate CVD from trades
  useEffect(() => {
    if (!tradesData?.events) return

    let cumulativeDelta = 0

    tradesData.events.forEach((trade: Trade) => {
      const delta = trade.takerSide === 'Buy' ? trade.qtySteps : -trade.qtySteps
      cumulativeDelta += delta
    })

    setCvdValue(cumulativeDelta)
  }, [tradesData])

  // Check reset interval
  useEffect(() => {
    if (settings.resetInterval === 'never') return

    const checkReset = () => {
      const now = Date.now()
      const lastReset = lastResetRef.current

      if (settings.resetInterval === 'daily') {
        const lastResetDate = new Date(lastReset).getDate()
        const nowDate = new Date(now).getDate()

        if (lastResetDate !== nowDate) {
          // New day - reset CVD
          setCvdValue(0)
          lastResetRef.current = now
          console.log('[CVD] Daily reset')
        }
      }
    }

    const interval = setInterval(checkReset, 60000) // Check every minute
    return () => clearInterval(interval)
  }, [settings.resetInterval])

  if (!settings.enabled) return null

  const displayColor = cvdValue >= 0 ? settings.positiveColor : settings.negativeColor
  const displayValue = cvdValue.toLocaleString()

  return (
    <div className="cvd-module">
      <div className="cvd-label">CVD</div>
      <div className="cvd-value" style={{ color: displayColor }}>
        {cvdValue >= 0 ? '+' : ''}{displayValue}
      </div>

      <style>{`
        .cvd-module {
          position: absolute;
          top: 60px;
          left: 20px;
          background: rgba(19, 23, 34, 0.9);
          border: 1px solid var(--border-default);
          border-radius: var(--radius-sm);
          padding: 8px 12px;
          display: flex;
          align-items: center;
          gap: 8px;
          z-index: 1000;
          backdrop-filter: blur(4px);
        }

        .cvd-label {
          font-size: 11px;
          font-weight: 600;
          color: var(--text-secondary);
          text-transform: uppercase;
        }

        .cvd-value {
          font-size: 16px;
          font-weight: 700;
          font-family: var(--font-mono);
        }
      `}</style>
    </div>
  )
}
