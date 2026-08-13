/**
 * BottomDock Component with Module Charts (Roadmap §11.6).
 *
 * Displays CVD, OrderFlow, Delta as separate mini-charts.
 * Active when visualization mode = 'panel'.
 */

import { useState } from 'react'
import CVDChart from './CVDChart'
import OrderFlowChart from './OrderFlowChart'

type DockTab = 'cvd' | 'orderflow' | 'delta'

export default function BottomDock() {
  const [activeTab, setActiveTab] = useState<DockTab>('cvd')

  return (
    <div className="bottom-dock">
      <div className="dock-tabs">
        <button
          className={`dock-tab ${activeTab === 'cvd' ? 'active' : ''}`}
          onClick={() => setActiveTab('cvd')}
        >
          CVD
        </button>
        <button
          className={`dock-tab ${activeTab === 'orderflow' ? 'active' : ''}`}
          onClick={() => setActiveTab('orderflow')}
        >
          OrderFlow
        </button>
        <button
          className={`dock-tab ${activeTab === 'delta' ? 'active' : ''}`}
          onClick={() => setActiveTab('delta')}
        >
          Delta
        </button>
      </div>

      <div className="dock-content">
        {activeTab === 'cvd' && <CVDChart />}
        {activeTab === 'orderflow' && <OrderFlowChart />}
        {activeTab === 'delta' && <div className="placeholder">Delta Chart (Coming Soon)</div>}
      </div>

      <style>{`
        .bottom-dock {
          height: 250px;
          border-top: 1px solid var(--border-default);
          background: var(--bg-secondary);
          display: flex;
          flex-direction: column;
        }

        .dock-tabs {
          display: flex;
          border-bottom: 1px solid var(--border-default);
          background: var(--bg-tertiary);
        }

        .dock-tab {
          padding: 8px 16px;
          background: none;
          border: none;
          border-bottom: 2px solid transparent;
          color: var(--text-secondary);
          font-size: 13px;
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
          border-bottom-color: var(--accent-blue);
          background: var(--bg-secondary);
        }

        .dock-content {
          flex: 1;
          overflow: hidden;
          position: relative;
        }

        .placeholder {
          display: flex;
          align-items: center;
          justify-content: center;
          height: 100%;
          color: var(--text-secondary);
          font-size: 14px;
        }
      `}</style>
    </div>
  )
}
