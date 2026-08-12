/**
 * StatusBar Component (Roadmap §11.1, §11.8).
 *
 * Показывает:
 * - feed ages (collector lag)
 * - gaps (missing sequences)
 * - analytics lag (orderflow/analytics worker lag)
 * - release/config hashes (git commit, config version)
 *
 * Quality/gap labels всегда видимы (acceptance criterion).
 */

export default function StatusBar() {
  // Mock data — будет заменено на реальные данные из /health и /metrics
  const status = {
    collectorLag: 123, // ms
    analyticsLag: 456, // ms
    gapCount: 0,
    lastUpdate: new Date().toISOString(),
    release: 'a72e11a',
    configHash: 'bb64cab',
  }

  return (
    <div className="status-bar">
      <div className="status-item">
        <span className="status-label">Collector:</span>
        <span className={`status-value ${status.collectorLag < 500 ? 'good' : 'warn'}`}>
          {status.collectorLag}ms
        </span>
      </div>

      <div className="status-item">
        <span className="status-label">Analytics:</span>
        <span className={`status-value ${status.analyticsLag < 1000 ? 'good' : 'warn'}`}>
          {status.analyticsLag}ms
        </span>
      </div>

      <div className="status-item">
        <span className="status-label">Gaps:</span>
        <span className={`status-value ${status.gapCount === 0 ? 'good' : 'error'}`}>
          {status.gapCount}
        </span>
      </div>

      <div className="status-separator" />

      <div className="status-item text-mono">
        <span className="status-label">Release:</span>
        <span className="status-value">{status.release}</span>
      </div>

      <div className="status-item text-mono">
        <span className="status-label">Config:</span>
        <span className="status-value">{status.configHash}</span>
      </div>

      <div className="status-item text-muted">
        <span className="status-label">Updated:</span>
        <span className="status-value">{new Date(status.lastUpdate).toLocaleTimeString()}</span>
      </div>

      <style>{`
        .status-bar {
          height: 24px;
          background: var(--bg-tertiary);
          border-top: 1px solid var(--border-default);
          display: flex;
          align-items: center;
          padding: 0 var(--spacing-md);
          gap: var(--spacing-md);
          font-size: 11px;
        }

        .status-item {
          display: flex;
          align-items: center;
          gap: 4px;
        }

        .status-label {
          color: var(--text-secondary);
          font-weight: 500;
        }

        .status-value {
          color: var(--text-primary);
        }

        .status-value.good {
          color: var(--status-success);
        }

        .status-value.warn {
          color: var(--status-warning);
        }

        .status-value.error {
          color: var(--status-error);
        }

        .status-separator {
          width: 1px;
          height: 16px;
          background: var(--border-default);
        }
      `}</style>
    </div>
  )
}
