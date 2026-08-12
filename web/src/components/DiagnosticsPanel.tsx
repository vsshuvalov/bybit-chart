/**
 * DiagnosticsPanel Component (Roadmap §11.8).
 *
 * Data Quality diagnostics:
 * - Feed ages (collector lag per feed)
 * - Gaps (missing sequences, missing updateIds)
 * - Analytics lag (orderflow/analytics worker processing lag)
 * - Connection status (WebSocket, IPC)
 * - Heatmap scope tooltip (standard-only до включения RPI)
 *
 * Acceptance criteria (§11.8):
 * - Quality/gap labels всегда видимы
 * - Feed ages раскрываются в tooltip
 * - Heatmap scope явно показывает coverage
 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

interface FeedStatus {
  feed: string
  lag: number
  lastUpdate: string
  status: 'good' | 'degraded' | 'stale'
  gaps?: number
}

interface DiagnosticsData {
  overall: 'good' | 'degraded' | 'stale'
  collectorLag: number
  analyticsLag: number
  totalGaps: number
  feeds: FeedStatus[]
  heatmapScope: 'standard-only' | 'rpi-enabled'
  connectionStatus: {
    websocket: boolean
    ipc: boolean
  }
}

export default function DiagnosticsPanel() {
  const [isOpen, setIsOpen] = useState(false)

  // Mock diagnostics — будет заменено на GET /api/v1/diagnostics
  const mockData: DiagnosticsData = {
    overall: 'good',
    collectorLag: 0,
    analyticsLag: 0,
    totalGaps: 0,
    feeds: [
      { feed: 'BTCUSDT trades', lag: 0, lastUpdate: '2s ago', status: 'good', gaps: 0 },
      { feed: 'ETHUSDT trades', lag: 0, lastUpdate: '1s ago', status: 'good', gaps: 0 },
      { feed: 'XRPUSDT trades', lag: 0, lastUpdate: '3s ago', status: 'good', gaps: 0 },
      { feed: 'BTCUSDT book', lag: 0, lastUpdate: 'N/A', status: 'stale', gaps: 0 },
      { feed: 'ETHUSDT book', lag: 0, lastUpdate: 'N/A', status: 'stale', gaps: 0 },
      { feed: 'XRPUSDT book', lag: 0, lastUpdate: 'N/A', status: 'stale', gaps: 0 },
    ],
    heatmapScope: 'standard-only',
    connectionStatus: {
      websocket: false,
      ipc: false,
    },
  }

  const { data = mockData } = useQuery({
    queryKey: ['diagnostics'],
    queryFn: async () => mockData, // будет: fetch('/api/v1/diagnostics')
    refetchInterval: 5000,
  })

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'good':
        return 'var(--status-success)'
      case 'degraded':
        return 'var(--status-warning)'
      case 'stale':
        return 'var(--status-error)'
      default:
        return 'var(--text-muted)'
    }
  }

  return (
    <div className="diagnostics-wrapper">
      <button
        className={`quality-badge ${data.overall}`}
        onClick={() => setIsOpen(!isOpen)}
        title="Click for diagnostics"
      >
        <span className="badge-dot" />
        Quality: {data.overall === 'good' ? 'Good' : data.overall === 'degraded' ? 'Degraded' : 'Stale'}
        <span className="badge-arrow">{isOpen ? '▼' : '▶'}</span>
      </button>

      {isOpen && (
        <>
          <div className="diagnostics-overlay" onClick={() => setIsOpen(false)} />
          <div className="diagnostics-panel">
            <div className="panel-header">
              <h3>Data Quality Diagnostics</h3>
              <button className="close-btn" onClick={() => setIsOpen(false)}>
                ✕
              </button>
            </div>

            <div className="panel-section">
              <div className="section-title">System Lag</div>
              <div className="metric-row">
                <span className="metric-label">Collector:</span>
                <span className={`metric-value ${data.collectorLag < 500 ? 'good' : 'warn'}`}>
                  {data.collectorLag}ms
                </span>
              </div>
              <div className="metric-row">
                <span className="metric-label">Analytics:</span>
                <span className={`metric-value ${data.analyticsLag < 1000 ? 'good' : 'warn'}`}>
                  {data.analyticsLag}ms
                </span>
              </div>
              <div className="metric-row">
                <span className="metric-label">Total Gaps:</span>
                <span className={`metric-value ${data.totalGaps === 0 ? 'good' : 'error'}`}>
                  {data.totalGaps}
                </span>
              </div>
            </div>

            <div className="panel-section">
              <div className="section-title">Feed Status</div>
              {data.feeds.map((feed, idx) => (
                <div key={idx} className="feed-row">
                  <span className="feed-dot" style={{ background: getStatusColor(feed.status) }} />
                  <span className="feed-name">{feed.feed}</span>
                  <span className="feed-lag text-muted">{feed.lastUpdate}</span>
                  {feed.gaps! > 0 && <span className="feed-gaps error">{feed.gaps} gaps</span>}
                </div>
              ))}
            </div>

            <div className="panel-section">
              <div className="section-title">Connection Status</div>
              <div className="metric-row">
                <span className="metric-label">WebSocket:</span>
                <span className={`metric-value ${data.connectionStatus.websocket ? 'good' : 'error'}`}>
                  {data.connectionStatus.websocket ? 'Connected' : 'Disconnected'}
                </span>
              </div>
              <div className="metric-row">
                <span className="metric-label">IPC:</span>
                <span className={`metric-value ${data.connectionStatus.ipc ? 'good' : 'error'}`}>
                  {data.connectionStatus.ipc ? 'Active' : 'Inactive'}
                </span>
              </div>
            </div>

            <div className="panel-section">
              <div className="section-title">Heatmap Scope</div>
              <div className="scope-notice">
                {data.heatmapScope === 'standard-only' ? (
                  <>
                    <span className="scope-icon">⚠️</span>
                    <span className="scope-text">
                      <strong>Standard-only</strong> — RPI feeds not enabled. Book coverage limited to
                      standard depth.
                    </span>
                  </>
                ) : (
                  <>
                    <span className="scope-icon">✓</span>
                    <span className="scope-text">
                      <strong>RPI-enabled</strong> — Full orderbook coverage with retail protection
                      indicators.
                    </span>
                  </>
                )}
              </div>
            </div>
          </div>
        </>
      )}

      <style>{`
        .diagnostics-wrapper {
          position: relative;
        }

        .quality-badge {
          height: 32px;
          padding: 0 var(--spacing-md);
          border: none;
          border-radius: var(--radius-sm);
          font-size: 12px;
          font-weight: 500;
          cursor: pointer;
          display: flex;
          align-items: center;
          gap: 6px;
          transition: all 0.2s;
        }

        .quality-badge.good {
          background: rgba(38, 166, 154, 0.15);
          color: var(--status-success);
          border: 1px solid var(--status-success);
        }

        .quality-badge.degraded {
          background: rgba(255, 152, 0, 0.15);
          color: var(--status-warning);
          border: 1px solid var(--status-warning);
        }

        .quality-badge.stale {
          background: rgba(239, 83, 80, 0.15);
          color: var(--status-error);
          border: 1px solid var(--status-error);
        }

        .quality-badge:hover {
          opacity: 0.8;
        }

        .badge-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: currentColor;
        }

        .badge-arrow {
          font-size: 10px;
        }

        .diagnostics-overlay {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          z-index: 999;
        }

        .diagnostics-panel {
          position: absolute;
          top: 40px;
          right: 0;
          width: 320px;
          max-height: 500px;
          background: var(--bg-secondary);
          border: 1px solid var(--border-highlight);
          border-radius: var(--radius-md);
          box-shadow: var(--shadow-lg);
          z-index: 1000;
          overflow-y: auto;
        }

        .panel-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: var(--spacing-md);
          border-bottom: 1px solid var(--border-default);
        }

        .panel-header h3 {
          font-size: 14px;
          font-weight: 600;
          color: var(--text-primary);
        }

        .close-btn {
          width: 24px;
          height: 24px;
          background: transparent;
          border: none;
          color: var(--text-secondary);
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          border-radius: var(--radius-sm);
          transition: all 0.2s;
        }

        .close-btn:hover {
          background: var(--bg-tertiary);
          color: var(--text-primary);
        }

        .panel-section {
          padding: var(--spacing-md);
          border-bottom: 1px solid var(--border-default);
        }

        .panel-section:last-child {
          border-bottom: none;
        }

        .section-title {
          font-size: 11px;
          font-weight: 600;
          color: var(--text-secondary);
          text-transform: uppercase;
          margin-bottom: var(--spacing-sm);
        }

        .metric-row {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 4px 0;
          font-size: 12px;
        }

        .metric-label {
          color: var(--text-secondary);
        }

        .metric-value {
          font-weight: 500;
          font-family: var(--font-mono);
        }

        .metric-value.good {
          color: var(--status-success);
        }

        .metric-value.warn {
          color: var(--status-warning);
        }

        .metric-value.error {
          color: var(--status-error);
        }

        .feed-row {
          display: flex;
          align-items: center;
          gap: var(--spacing-sm);
          padding: 4px 0;
          font-size: 12px;
        }

        .feed-dot {
          width: 6px;
          height: 6px;
          border-radius: 50%;
          flex-shrink: 0;
        }

        .feed-name {
          flex: 1;
          color: var(--text-primary);
        }

        .feed-lag {
          font-size: 10px;
        }

        .feed-gaps {
          font-size: 10px;
          padding: 2px 4px;
          background: rgba(239, 83, 80, 0.15);
          border-radius: 2px;
        }

        .scope-notice {
          display: flex;
          gap: var(--spacing-sm);
          padding: var(--spacing-sm);
          background: var(--bg-tertiary);
          border-radius: var(--radius-sm);
          font-size: 11px;
          line-height: 1.4;
        }

        .scope-icon {
          font-size: 14px;
          flex-shrink: 0;
        }

        .scope-text {
          color: var(--text-secondary);
        }

        .scope-text strong {
          color: var(--text-primary);
        }
      `}</style>
    </div>
  )
}
