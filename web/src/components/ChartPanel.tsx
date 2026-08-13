/**
 * ChartPanel Component (Roadmap §11.1, §11.5).
 *
 * Center panel: TradingView Advanced Charts with drawing tools.
 * Replaces lightweight-charts for built-in drawing support.
 *
 * Includes overlay modules: CVD, OrderFlow Imbalance
 */

import { useState } from 'react'
import { useViewStore } from '../store'
import TradingViewChart from './TradingViewChart'
import CVDModule from '../modules/CVDModule'
import OrderFlowModule from '../modules/OrderFlowModule'

export default function ChartPanel() {
  const { symbol } = useViewStore()

  // Module settings (later: load from workspace)
  const [cvdSettings] = useState({
    enabled: true,
    resetInterval: 'daily' as const,
    smoothing: 14,
    positiveColor: '#26a69a',
    negativeColor: '#ef5350',
  })

  const [orderFlowSettings] = useState({
    enabled: true,
    imbalanceThreshold: 2.0,
    volumeMinimum: 10000,
    algorithm: 'ratio' as const,
    buyColor: '#26a69a',
    sellColor: '#ef5350',
    filterSmallTrades: true,
    minTradeSize: 100,
  })

  return (
    <div className="chart-panel">
      <TradingViewChart />

      {/* Overlay Modules */}
      <CVDModule symbol={symbol} settings={cvdSettings} />
      <OrderFlowModule symbol={symbol} settings={orderFlowSettings} />
    </div>
  )
}
