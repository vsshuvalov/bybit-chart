/**
 * ChartPanel Component (Roadmap §11.1, §11.5).
 *
 * Center panel: TradingView Advanced Charts with drawing tools.
 * Includes overlay modules: CVD, OrderFlow Imbalance.
 *
 * Two visualization modes:
 * - 'overlay': Modules as info boxes over chart
 * - 'panel': Modules as mini-charts in BottomDock
 */

import { useState } from 'react'
import { useViewStore } from '../store'
import { useModuleVisualizationStore } from '../store/moduleVisualizationStore'
import TradingViewChart from './TradingViewChart'
import CVDModule from '../modules/CVDModule'
import OrderFlowModule from '../modules/OrderFlowModule'
import BottomDockModules from './BottomDockModules'

export default function ChartPanel() {
  const { symbol } = useViewStore()
  const { mode } = useModuleVisualizationStore()

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
    <>
      <div className="chart-panel" style={{ flex: mode === 'panel' ? '1' : undefined }}>
        <TradingViewChart />

        {/* Overlay Mode: Info boxes */}
        {mode === 'overlay' && (
          <>
            <CVDModule symbol={symbol} settings={cvdSettings} />
            <OrderFlowModule symbol={symbol} settings={orderFlowSettings} />
          </>
        )}
      </div>

      {/* Panel Mode: BottomDock with charts */}
      {mode === 'panel' && <BottomDockModules />}
    </>
  )
}
