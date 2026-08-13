/**
 * ChartPanel Component (Roadmap §11.1, §11.5).
 *
 * Center panel: TradingView Advanced Charts with drawing tools.
 * Replaces lightweight-charts for built-in drawing support.
 */

import TradingViewChart from './TradingViewChart'

export default function ChartPanel() {
  return (
    <div className="chart-panel">
      <TradingViewChart />
    </div>
  )
}
