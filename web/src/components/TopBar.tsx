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

import { useState } from 'react'
import { useViewStore, Timeframe, Environment, TradingState } from '../store'
import { useModuleVisualizationStore } from '../store/moduleVisualizationStore'
import DiagnosticsPanel from './DiagnosticsPanel'
import SettingsPanel from './SettingsPanel'
import WorkspaceSelector from './WorkspaceSelector'
import { getModuleSchema } from '../schemas/moduleSchemas'

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

  const [isRecording, setIsRecording] = useState(false)
  const [recordingStatus, setRecordingStatus] = useState<string>('')
  const [settingsPanelOpen, setSettingsPanelOpen] = useState(false)
  const [selectedModuleId, setSelectedModuleId] = useState<string | null>(null)
  const [currentWorkspaceId, setCurrentWorkspaceId] = useState<string>(() => {
    // Load from localStorage
    return localStorage.getItem('currentWorkspaceId') || ''
  })

  const handleSelectWorkspace = (workspaceId: string) => {
    console.log('[TopBar] Switch to workspace:', workspaceId)
    setCurrentWorkspaceId(workspaceId)
    localStorage.setItem('currentWorkspaceId', workspaceId)
    // TODO: Load workspace layout/indicators/drawings
  }

  const handleOpenSettings = (moduleId: string) => {
    setSelectedModuleId(moduleId)
    setSettingsPanelOpen(true)
  }

  const handleSaveSettings = (settings: Record<string, any>) => {
    console.log('[TopBar] Save settings:', settings)
    // TODO: Save to workspace via persistence API
    setSettingsPanelOpen(false)
  }

  const toggleRecording = async () => {
    try {
      if (!isRecording) {
        // Начать запись
        const response = await fetch('/api/v1/recording/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ symbol }),
        })

        if (response.ok) {
          setIsRecording(true)
          setRecordingStatus(`Recording ${symbol}`)
          console.log('[Recording] Started for', symbol)
        } else {
          const error = await response.text()
          setRecordingStatus(`Error: ${error}`)
        }
      } else {
        // Остановить запись
        const response = await fetch('/api/v1/recording/stop', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ symbol }),
        })

        if (response.ok) {
          setIsRecording(false)
          setRecordingStatus('')
          console.log('[Recording] Stopped for', symbol)
        }
      }
    } catch (err) {
      console.error('[Recording] Error:', err)
      setRecordingStatus('Connection error')
    }
  }

  const symbols = [
    'BTCUSDT',
    'ETHUSDT',
    'SOLUSDT',
    'XRPUSDT',
    'DOGEUSDT',
    'ADAUSDT',
    'AVAXUSDT',
    'DOTUSDT',
    'MATICUSDT',
    'LINKUSDT',
    'UNIUSDT',
    'ATOMUSDT',
    'LTCUSDT',
    'BCHUSDT',
    'NEARUSDT',
    'ALGOUSDT',
    'VETUSDT',
    'ICPUSDT',
    'FILUSDT',
    'APTUSDT',
    'ARBUSDT',
    'OPUSDT',
    'INJUSDT',
    'SUIUSDT',
    'PEPEUSDT',
    'SHIBUSDT',
    'WLDUSDT',
    'THETAUSDT',
    'RNDRUSDT',
  ]
  const timeframes: Timeframe[] = ['1m', '5m', '15m', '30m', '1h', '4h', '1d']
  const environments: Environment[] = ['OFFLINE', 'DEMO', 'TESTNET', 'LIVE']
  const tradingStates: TradingState[] = ['Enabled', 'SafeMode', 'Halted']

  return (
    <div className="top-bar">
      <div className="top-bar-left">
        <WorkspaceSelector
          currentWorkspaceId={currentWorkspaceId}
          onSelectWorkspace={handleSelectWorkspace}
        />

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
          className="settings-btn"
          onClick={() => handleOpenSettings('orderflow_imbalance')}
          title="Module Settings"
        >
          ⚙️
        </button>

        <ModuleVisualizationToggle />

        <button
          className={`mode-toggle ${isReplayMode ? 'replay' : 'live'}`}
          onClick={toggleReplayMode}
        >
          {isReplayMode ? '📹 Replay' : '🔴 Live'}
        </button>

        <button
          className={`record-btn ${isRecording ? 'recording' : ''}`}
          onClick={toggleRecording}
          title={recordingStatus || 'Start recording trades to database'}
        >
          {isRecording ? '⏹ Stop' : '⏺ REC'}
        </button>

        <DiagnosticsPanel />

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

        .record-btn {
          height: 32px;
          padding: 0 var(--spacing-md);
          border: 1px solid var(--border-default);
          border-radius: var(--radius-sm);
          font-size: 13px;
          font-weight: 500;
          cursor: pointer;
          transition: all 0.2s;
          background: var(--bg-tertiary);
          color: var(--text-primary);
        }

        .record-btn:hover {
          background: var(--bg-primary);
          border-color: var(--border-highlight);
        }

        .record-btn.recording {
          background: rgba(239, 83, 80, 0.15);
          color: #ef5350;
          border-color: #ef5350;
          animation: pulse-recording 2s infinite;
        }

        @keyframes pulse-recording {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.6; }
        }

        .env-select,
        .trading-state {
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

        .settings-btn {
          background: var(--bg-tertiary);
          border: 1px solid var(--border-default);
          color: var(--text-secondary);
          padding: 6px 12px;
          border-radius: var(--radius-sm);
          font-size: 18px;
          cursor: pointer;
          transition: all 0.2s;
        }

        .settings-btn:hover {
          background: var(--bg-primary);
          color: var(--text-primary);
          border-color: var(--border-highlight);
        }
      `}</style>

      {/* Settings Panel Overlay */}
      {settingsPanelOpen && selectedModuleId && (
        <SettingsPanel
          schema={getModuleSchema(selectedModuleId)!}
          onSave={handleSaveSettings}
          onClose={() => setSettingsPanelOpen(false)}
        />
      )}
    </div>
  )
}

// ========== Module Visualization Toggle ==========

function ModuleVisualizationToggle() {
  const { mode, setMode } = useModuleVisualizationStore()

  return (
    <button
      className="viz-toggle"
      onClick={() => setMode(mode === 'overlay' ? 'panel' : 'overlay')}
      title={`Visualization: ${mode === 'overlay' ? 'Overlay' : 'Panel'}`}
    >
      {mode === 'overlay' ? '📊' : '📈'}
      <style>{`
        .viz-toggle {
          background: var(--bg-tertiary);
          border: 1px solid var(--border-default);
          color: var(--text-primary);
          padding: 6px 12px;
          border-radius: var(--radius-sm);
          font-size: 18px;
          cursor: pointer;
          transition: all 0.2s;
        }

        .viz-toggle:hover {
          background: var(--bg-primary);
          border-color: var(--border-highlight);
        }
      `}</style>
    </button>
  )
}
