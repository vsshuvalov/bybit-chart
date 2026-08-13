/**
 * ChartPanel Component (Roadmap §11.1, §11.5).
 *
 * Center panel: Lightweight Charts with custom drawing tools.
 * Replaces TradingView widget for full control.
 *
 * Supports two visualization modes for indicators:
 * - Overlay: CVD/OrderFlow as overlays on main chart
 * - Separate: CVD/OrderFlow in BottomDock panels
 */

import { useState } from 'react'
import { useModuleVisualizationStore } from '../store/moduleVisualizationStore'
import MainChart from './MainChart'
import BottomDockModules from './BottomDockModules'

export default function ChartPanel() {
  const { mode } = useModuleVisualizationStore()

  // Module settings (later: load from workspace)
  const [showCVDOverlay] = useState(mode === 'overlay')
  const [showOrderFlowOverlay] = useState(mode === 'overlay')

  return (
    <>
      <div className="chart-panel" style={{ flex: mode === 'panel' ? '1' : undefined }}>
        <MainChart
          showCVDOverlay={showCVDOverlay}
          showOrderFlowOverlay={showOrderFlowOverlay}
        />
      </div>

      {/* Panel Mode: BottomDock with separate charts */}
      {mode === 'panel' && <BottomDockModules />}
    </>
  )
}
