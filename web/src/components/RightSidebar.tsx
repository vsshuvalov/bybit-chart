/**
 * RightSidebar Component (Roadmap §11.4).
 *
 * Tabs:
 * - Watchlist: BTCUSDT/ETHUSDT/XRPUSDT + Last/24h%/spread/quality/position/PnL
 * - DOM: Bid/Ask size, cumulative, estimated executed, pulling/stacking
 * - Tape: time, price, side, base/quote volume, BT/RPI flags
 * - Levels: POC/VAH/VAL/VWAP/walls/user levels
 * - Orders: Order ticket + Active orders
 * - Positions: Positions + Fills/history + Risk status
 * - AI: Ask/Explain + Strategy proposals + Backtest queue
 */

import { useUIStore } from '../store'
import Watchlist from './Watchlist'

export default function RightSidebar() {
  const { rightSidebarTab, setRightSidebarTab } = useUIStore()

  const tabs = [
    { id: 'watchlist', label: 'Watchlist' },
    { id: 'dom', label: 'DOM' },
    { id: 'tape', label: 'Tape' },
    { id: 'levels', label: 'Levels' },
  ] as const

  return (
    <div className="right-sidebar">
      <div className="sidebar-tabs">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            className={`tab-btn ${rightSidebarTab === tab.id ? 'active' : ''}`}
            onClick={() => setRightSidebarTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="sidebar-content">
        {rightSidebarTab === 'watchlist' && <Watchlist />}
        {rightSidebarTab === 'dom' && <DOMPanel />}
        {rightSidebarTab === 'tape' && <TapePanel />}
        {rightSidebarTab === 'levels' && <LevelsPanel />}
      </div>

      <style>{`
        .right-sidebar {
          width: 280px;
          background: var(--bg-secondary);
          border-left: 1px solid var(--border-default);
          display: flex;
          flex-direction: column;
        }

        .sidebar-tabs {
          display: flex;
          border-bottom: 1px solid var(--border-default);
          background: var(--bg-tertiary);
        }

        .tab-btn {
          flex: 1;
          height: 36px;
          background: transparent;
          border: none;
          border-bottom: 2px solid transparent;
          color: var(--text-secondary);
          font-size: 12px;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.2s;
        }

        .tab-btn:hover {
          color: var(--text-primary);
          background: var(--bg-secondary);
        }

        .tab-btn.active {
          color: var(--accent-blue);
          border-bottom-color: var(--accent-blue);
          background: var(--bg-secondary);
        }

        .sidebar-content {
          flex: 1;
          overflow-y: auto;
        }
      `}</style>
    </div>
  )
}

// Placeholder panels (will implement in separate tasks)

function DOMPanel() {
  return (
    <div style={{ padding: 'var(--spacing-md)', color: 'var(--text-muted)' }}>
      DOM Panel — TODO
      <div style={{ marginTop: '8px', fontSize: '12px' }}>
        Bid/Ask depth, cumulative volume, pulling/stacking detection
      </div>
    </div>
  )
}

function TapePanel() {
  return (
    <div style={{ padding: 'var(--spacing-md)', color: 'var(--text-muted)' }}>
      Tape Panel — TODO
      <div style={{ marginTop: '8px', fontSize: '12px' }}>
        Recent trades: time, price, side, volume, BT/RPI flags
      </div>
    </div>
  )
}

function LevelsPanel() {
  return (
    <div style={{ padding: 'var(--spacing-md)', color: 'var(--text-muted)' }}>
      Levels Panel — TODO
      <div style={{ marginTop: '8px', fontSize: '12px' }}>
        POC/VAH/VAL, VWAP, walls, user-drawn levels
      </div>
    </div>
  )
}
