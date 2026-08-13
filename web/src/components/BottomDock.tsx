/**
 * BottomDock Component (Roadmap §11.1).
 *
 * Tabs:
 * - Delta/CVD: cumulative volume delta charts
 * - OI/Funding: open interest + funding rate
 * - Strategy log: signal events + entry/exit markers
 * - Replay metrics: playback speed, event rate, time range
 */

import { useUIStore } from '../store'

export default function BottomDock() {
  const { bottomDockTab, setBottomDockTab } = useUIStore()

  const tabs = [
    { id: 'delta', label: 'Delta / CVD' },
    { id: 'oi', label: 'OI / Funding' },
    { id: 'strategy', label: 'Strategy Log' },
    { id: 'replay', label: 'Replay' },
  ] as const

  return (
    <div className="bottom-dock">
      <div className="dock-tabs">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            className={`dock-tab ${bottomDockTab === tab.id ? 'active' : ''}`}
            onClick={() => setBottomDockTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="dock-content">
        {bottomDockTab === 'delta' && <DeltaCVDPanel />}
        {bottomDockTab === 'oi' && <OIFundingPanel />}
        {bottomDockTab === 'strategy' && <StrategyLogPanel />}
        {bottomDockTab === 'replay' && <ReplayMetricsPanel />}
      </div>

      <style>{`
        .bottom-dock {
          height: 200px;
          background: var(--bg-secondary);
          border-top: 1px solid var(--border-default);
          display: flex;
          flex-direction: column;
        }

        .dock-tabs {
          display: flex;
          gap: 2px;
          padding: var(--spacing-xs) var(--spacing-md);
          background: var(--bg-tertiary);
          border-bottom: 1px solid var(--border-default);
        }

        .dock-tab {
          padding: 6px 12px;
          background: transparent;
          border: none;
          border-radius: var(--radius-sm);
          color: var(--text-secondary);
          font-size: 12px;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.2s;
        }

        .dock-tab:hover {
          color: var(--text-primary);
          background: var(--bg-secondary);
        }

        .dock-tab.active {
          color: var(--accent-blue);
          background: var(--bg-secondary);
        }

        .dock-content {
          flex: 1;
          overflow: auto;
        }
      `}</style>
    </div>
  )
}

// Placeholder panels

function DeltaCVDPanel() {
  return (
    <div style={{ padding: 'var(--spacing-md)', color: 'var(--text-muted)' }}>
      Delta / CVD Panel — TODO
      <div style={{ marginTop: '8px', fontSize: '12px' }}>
        GET /api/v1/analytics/delta + /api/v1/analytics/cvd
      </div>
    </div>
  )
}

function OIFundingPanel() {
  return (
    <div style={{ padding: 'var(--spacing-md)', color: 'var(--text-muted)' }}>
      OI / Funding Panel — TODO
      <div style={{ marginTop: '8px', fontSize: '12px' }}>
        Open Interest + Funding Rate (backend endpoint pending)
      </div>
    </div>
  )
}

function StrategyLogPanel() {
  return (
    <div style={{ padding: 'var(--spacing-md)', color: 'var(--text-muted)' }}>
      Strategy Log Panel — TODO
      <div style={{ marginTop: '8px', fontSize: '12px' }}>
        Signal events, entry/exit markers, performance metrics
      </div>
    </div>
  )
}

function ReplayMetricsPanel() {
  return (
    <div style={{ padding: 'var(--spacing-md)', color: 'var(--text-muted)' }}>
      Replay Metrics Panel — TODO
      <div style={{ marginTop: '8px', fontSize: '12px' }}>
        Playback speed, event rate, time range selector
      </div>
    </div>
  )
}
