/**
 * OrderFlow Imbalance Module (Roadmap §11.6).
 *
 * Visualizes bid/ask imbalance from trade flow.
 * Formula: imbalance = buyVolume / sellVolume
 *
 * Displays:
 * - Imbalance ratio (e.g., 2.5x more buy pressure)
 * - Color coded: green (buy > sell), red (sell > buy), neutral (balanced)
 * - Alert when threshold exceeded
 */

import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import axios from 'axios'

interface Trade {
  timestampUs: number
  takerSide: 'Buy' | 'Sell'
  qtySteps: number
  priceTicks: number
}

interface OrderFlowSettings {
  enabled: boolean
  imbalanceThreshold: number
  volumeMinimum: number
  algorithm: 'ratio' | 'delta' | 'weighted'
  buyColor: string
  sellColor: string
  filterSmallTrades: boolean
  minTradeSize: number
}

interface OrderFlowModuleProps {
  symbol: string
  settings: OrderFlowSettings
}

export default function OrderFlowModule({ symbol, settings }: OrderFlowModuleProps) {
  const [buyVolume, setBuyVolume] = useState(0)
  const [sellVolume, setSellVolume] = useState(0)
  const [imbalance, setImbalance] = useState(0)
  const [alert, setAlert] = useState(false)

  // Fetch recent trades
  const { data: tradesData } = useQuery({
    queryKey: ['trades', symbol],
    queryFn: async () => {
      const response = await axios.get(`http://83.147.234.167/api/v1/trades`, {
        params: { symbol, limit: 500 },
      })
      return response.data
    },
    refetchInterval: 2000, // Refetch every 2 seconds
    enabled: settings.enabled,
  })

  // Calculate imbalance
  useEffect(() => {
    if (!tradesData?.events) return

    let totalBuyVolume = 0
    let totalSellVolume = 0

    tradesData.events.forEach((trade: Trade) => {
      // Filter small trades if enabled
      if (settings.filterSmallTrades && trade.qtySteps < settings.minTradeSize) {
        return
      }

      if (trade.takerSide === 'Buy') {
        totalBuyVolume += trade.qtySteps
      } else {
        totalSellVolume += trade.qtySteps
      }
    })

    setBuyVolume(totalBuyVolume)
    setSellVolume(totalSellVolume)

    // Calculate imbalance based on algorithm
    let calculatedImbalance = 0

    if (settings.algorithm === 'ratio') {
      calculatedImbalance = totalSellVolume > 0 ? totalBuyVolume / totalSellVolume : 0
    } else if (settings.algorithm === 'delta') {
      calculatedImbalance = totalBuyVolume - totalSellVolume
    }

    setImbalance(calculatedImbalance)

    // Check threshold alert
    if (settings.algorithm === 'ratio' && calculatedImbalance > settings.imbalanceThreshold) {
      setAlert(true)
      setTimeout(() => setAlert(false), 3000) // Clear alert after 3s
    }
  }, [tradesData, settings])

  if (!settings.enabled) return null

  const isBuyPressure = buyVolume > sellVolume
  const displayColor = isBuyPressure ? settings.buyColor : settings.sellColor
  const displayValue = settings.algorithm === 'ratio'
    ? `${imbalance.toFixed(2)}x`
    : imbalance.toLocaleString()

  return (
    <div className={`orderflow-module ${alert ? 'alert' : ''}`}>
      <div className="orderflow-label">Imbalance</div>
      <div className="orderflow-value" style={{ color: displayColor }}>
        {displayValue}
      </div>
      <div className="orderflow-volumes">
        <span style={{ color: settings.buyColor }}>↑{buyVolume.toLocaleString()}</span>
        <span style={{ color: settings.sellColor }}>↓{sellVolume.toLocaleString()}</span>
      </div>

      <style>{`
        .orderflow-module {
          position: absolute;
          top: 60px;
          left: 180px;
          background: rgba(19, 23, 34, 0.9);
          border: 1px solid var(--border-default);
          border-radius: var(--radius-sm);
          padding: 8px 12px;
          display: flex;
          flex-direction: column;
          gap: 4px;
          z-index: 1000;
          backdrop-filter: blur(4px);
          transition: all 0.2s;
        }

        .orderflow-module.alert {
          border-color: var(--accent-orange);
          box-shadow: 0 0 12px rgba(255, 152, 0, 0.4);
        }

        .orderflow-label {
          font-size: 11px;
          font-weight: 600;
          color: var(--text-secondary);
          text-transform: uppercase;
        }

        .orderflow-value {
          font-size: 16px;
          font-weight: 700;
          font-family: var(--font-mono);
        }

        .orderflow-volumes {
          display: flex;
          gap: 12px;
          font-size: 11px;
          font-family: var(--font-mono);
        }
      `}</style>
    </div>
  )
}
