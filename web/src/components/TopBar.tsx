/**
 * TopBar Component (Roadmap §11.2).
 *
 * Controls:
 * 1. Workspace: открыть, сохранить, создать копию, export/import
 * 2. Symbol: BTCUSDT, ETHUSDT, XRPUSDT
 * 3. Timeframe: 1m/5m/15m/30m/1h/4h/1d
 * 4. Bar type: time/tick/volume/range/delta (после реализации backend)
 * 5. Price source: Last/Mid/Mark/Index
 * 6. Live/Replay switch с явной цветовой границей
 * 7. Data Quality badge с раскрытием feed ages/gaps
 * 8. Account/environment: OFFLINE, DEMO, TESTNET, LIVE
 * 9. Emergency state: Trading Enabled / Safe Mode / Halted
 */

import { useViewStore, Timeframe, Environment, TradingState } from '../store'

export default function TopBar() {
  const {
    symbol,
    timeframe,
    environment,
    tradingState,
    isReplayMode,
    setSymbol,
    setTimeframe,
    setEnvironment,
    setTradingState,
    toggleReplayMode,
  } = useViewStore()

  const symbols = ['BTCUSDT', 'ETHUSDT', 'XRPUSDT']
  const timeframes: Timeframe[] = ['1m', '5m', '15m', '30m', '1h', '4h', '1d']
  const environments: Environment[] = ['OFFLINE', 'DEMO', 'TESTNET', 'LIVE']
  const tradingStates: TradingState[] = ['Enabled', 'SafeMode', 'Halted']

  return (
    <div className="top-bar">
      <div className="top-bar-left">
        <button className="workspace-btn">Workspace ▾</button>

        <div className="separator" />

        <select value={symbol} onChange={(e) => setSymbol(e.target.value)} className="symbol-select">
          {symbols.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>

        <div className="tf-group">
          {timeframes.map((tf) => (
            <button
              key={tf}
              className={`tf-btn ${timeframe === tf ? 'active' : ''}`}
              onClick={() => setTimeframe(tf)}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>

      <div className="top-bar-right">
        <button
          className={`mode-toggle ${isReplayMode ? 'replay' : 'live'}`}
          onClick={toggleReplayMode}
        >
          {isReplayMode ? '📹 Replay' : '🔴 Live'}
        </button>

        <div className="quality-badge good">Quality: Good</div>

        <select
          value={environment}
          onChange={(e) => setEnvironment(e.target.value as Environment)}
          className="env-select"
        >
          {environments.map((env) => (
            <option key={env} value={env}>
              {env}
            </option>
          ))}
        </select>

        <select
          value={tradingState}
          onChange={(e) => setTradingState(e.target.value as TradingState)}
          className={`trading-state ${tradingState.toLowerCase()}`}
        >
          {tradingStates.map((state) => (
            <option key={state} value={state}>
              {state}
            </option>
          ))}
        </select>
      </div>

      <style>{`
        .top-bar {
          display: flex;
          justify-content: space-between;
          align-items: center;
          height: 48px;
          padding: 0 var(--spacing-md);
          background: var(--bg-secondary);
          border-bottom: 1px solid var(--border-default);
          gap: var(--spacing-md);
        }

        .top-bar-left,
        .top-bar-right {
          display: flex;
          align-items: center;
          gap: var(--spacing-sm);
        }

        .workspace-btn,
        .symbol-select,
        .env-select,
        .trading-state,
        .tf-btn {
          height: 32px;
          padding: 0 var(--spacing-md);
          background: var(--bg-tertiary);
          border: 1px solid var(--border-default);
          border-radius: var(--radius-sm);
          color: var(--text-primary);
          font-size: 13px;
          cursor: pointer;
          transition: all 0.2s;
        }

        .workspace-btn:hover,
        .symbol-select:hover,
        .env-select:hover,
        .trading-state:hover,
        .tf-btn:hover {
          background: var(--bg-primary);
          border-color: var(--border-highlight);
        }

        .tf-group {
          display: flex;
          gap: 2px;
        }

        .tf-btn {
          min-width: 40px;
          padding: 0 8px;
        }

        .tf-btn.active {
          background: var(--accent-blue);
          border-color: var(--accent-blue);
          color: white;
        }

        .mode-toggle {
          height: 32px;
          padding: 0 var(--spacing-md);
          border: none;
          border-radius: var(--radius-sm);
          font-size: 13px;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.2s;
        }

        .mode-toggle.live {
          background: var(--status-error);
          color: white;
        }

        .mode-toggle.replay {
          background: var(--accent-orange);
          color: white;
        }

        .quality-badge {
          height: 32px;
          padding: 0 var(--spacing-md);
          border-radius: var(--radius-sm);
          font-size: 12px;
          display: flex;
          align-items: center;
          font-weight: 500;
        }

        .quality-badge.good {
          background: rgba(38, 166, 154, 0.15);
          color: var(--status-success);
          border: 1px solid var(--status-success);
        }

        .trading-state.enabled {
          background: rgba(38, 166, 154, 0.15);
          color: var(--status-success);
          border-color: var(--status-success);
        }

        .trading-state.safemode {
          background: rgba(255, 152, 0, 0.15);
          color: var(--status-warning);
          border-color: var(--status-warning);
        }

        .trading-state.halted {
          background: rgba(239, 83, 80, 0.15);
          color: var(--status-error);
          border-color: var(--status-error);
        }

        .separator {
          width: 1px;
          height: 24px;
          background: var(--border-default);
        }

        select {
          cursor: pointer;
          outline: none;
        }

        select:focus,
        button:focus {
          outline: 2px solid var(--accent-blue);
          outline-offset: 2px;
        }
      `}</style>
    </div>
  )
}
