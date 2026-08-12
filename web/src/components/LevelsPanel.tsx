/**
 * Levels Panel Component (Roadmap §11.4).
 *
 * Key price levels:
 * - POC (Point of Control): highest volume node
 * - VAH/VAL (Value Area High/Low): 70% volume boundaries
 * - VWAP (Volume Weighted Average Price)
 * - Walls: large limit orders (support/resistance)
 * - User-drawn levels
 *
 * Each level can be toggled on/off and shown on chart.
 */

import { useState } from 'react'
import { useViewStore } from '../store'

interface Level {
  id: string
  type: 'poc' | 'vah' | 'val' | 'vwap' | 'wall' | 'user'
  label: string
  price: number
  enabled: boolean
  color: string
  description?: string
}

export default function LevelsPanel() {
  const { symbol } = useViewStore()

  // Mock levels — будет заменено на данные из analytics API
  const basePrice = symbol === 'BTCUSDT' ? 50000 : symbol === 'ETHUSDT' ? 2500 : 0.5

  const [levels, setLevels] = useState<Level[]>([
    {
      id: 'poc-1',
      type: 'poc',
      label: 'POC',
      price: basePrice,
      enabled: true,
      color: '#2962ff',
      description: 'Point of Control (highest volume)',
    },
    {
      id: 'vah-1',
      type: 'vah',
      label: 'VAH',
      price: basePrice * 1.01,
      enabled: true,
      color: '#26a69a',
      description: 'Value Area High (70% volume upper bound)',
    },
    {
      id: 'val-1',
      type: 'val',
      label: 'VAL',
      price: basePrice * 0.99,
      enabled: true,
      color: '#ef5350',
      description: 'Value Area Low (70% volume lower bound)',
    },
    {
      id: 'vwap-1',
      type: 'vwap',
      label: 'VWAP',
      price: basePrice * 1.002,
      enabled: true,
      color: '#ff9800',
      description: 'Volume Weighted Average Price',
    },
    {
      id: 'wall-bid',
      type: 'wall',
      label: 'Bid Wall',
      price: basePrice * 0.985,
      enabled: false,
      color: '#26a69a',
      description: 'Large bid order (support)',
    },
    {
      id: 'wall-ask',
      type: 'wall',
      label: 'Ask Wall',
      price: basePrice * 1.015,
      enabled: false,
      color: '#ef5350',
      description: 'Large ask order (resistance)',
    },
  ])

  const toggleLevel = (id: string) => {
    setLevels((prev) => prev.map((l) => (l.id === id ? { ...l, enabled: !l.enabled } : l)))
  }

  const typeIcons: Record<string, string> = {
    poc: '◆',
    vah: '▲',
    val: '▼',
    vwap: '~',
    wall: '█',
    user: '◉',
  }

  return (
    <div className="levels-panel">
      <div className="levels-header">
        <div className="header-title">Price Levels</div>
        <button className="add-level-btn" title="Add custom level">
          +
        </button>
      </div>

      <div className="levels-list">
        {levels.map((level) => (
          <div key={level.id} className={`level-row ${level.enabled ? 'enabled' : 'disabled'}`}>
            <button
              className="level-toggle"
              onClick={() => toggleLevel(level.id)}
              style={{ color: level.enabled ? level.color : 'var(--text-muted)' }}
            >
              <span className="level-icon">{typeIcons[level.type]}</span>
            </button>

            <div className="level-info">
              <div className="level-label">
                {level.label}
                <span className="level-type text-muted">{level.type.toUpperCase()}</span>
              </div>
              <div className="level-price text-mono">{level.price.toFixed(2)}</div>
              {level.description && <div className="level-desc text-muted">{level.description}</div>}
            </div>

            <div className="level-actions">
              <button className="action-btn" title="Edit level">
                ✏
              </button>
              {level.type === 'user' && (
                <button className="action-btn danger" title="Delete level">
                  🗑
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      <style>{`
        .levels-panel {
          display: flex;
          flex-direction: column;
          height: 100%;
          font-size: 12px;
        }

        .levels-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: var(--spacing-sm) var(--spacing-md);
          background: var(--bg-tertiary);
          border-bottom: 1px solid var(--border-default);
        }

        .header-title {
          font-size: 11px;
          font-weight: 600;
          color: var(--text-secondary);
          text-transform: uppercase;
        }

        .add-level-btn {
          width: 24px;
          height: 24px;
          background: var(--accent-blue);
          border: none;
          border-radius: var(--radius-sm);
          color: white;
          font-size: 18px;
          line-height: 1;
          cursor: pointer;
          transition: all 0.2s;
        }

        .add-level-btn:hover {
          background: var(--accent-blue);
          opacity: 0.8;
        }

        .levels-list {
          flex: 1;
          overflow-y: auto;
        }

        .level-row {
          display: flex;
          gap: var(--spacing-sm);
          padding: var(--spacing-sm) var(--spacing-md);
          border-bottom: 1px solid var(--bg-tertiary);
          transition: background 0.15s;
        }

        .level-row:hover {
          background: var(--bg-tertiary);
        }

        .level-row.disabled {
          opacity: 0.5;
        }

        .level-toggle {
          width: 24px;
          height: 24px;
          background: transparent;
          border: 1px solid var(--border-default);
          border-radius: var(--radius-sm);
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          transition: all 0.2s;
          flex-shrink: 0;
        }

        .level-toggle:hover {
          border-color: var(--border-highlight);
          background: var(--bg-primary);
        }

        .level-icon {
          font-size: 14px;
        }

        .level-info {
          flex: 1;
          display: flex;
          flex-direction: column;
          gap: 2px;
        }

        .level-label {
          display: flex;
          gap: var(--spacing-sm);
          align-items: center;
          font-weight: 500;
        }

        .level-type {
          font-size: 9px;
          padding: 1px 4px;
          background: var(--bg-tertiary);
          border-radius: 2px;
        }

        .level-price {
          font-size: 13px;
          color: var(--text-primary);
        }

        .level-desc {
          font-size: 10px;
          line-height: 1.3;
        }

        .level-actions {
          display: flex;
          gap: 4px;
          align-items: center;
        }

        .action-btn {
          width: 24px;
          height: 24px;
          background: transparent;
          border: 1px solid transparent;
          border-radius: var(--radius-sm);
          color: var(--text-secondary);
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          transition: all 0.2s;
          font-size: 12px;
        }

        .action-btn:hover {
          background: var(--bg-primary);
          border-color: var(--border-highlight);
          color: var(--text-primary);
        }

        .action-btn.danger:hover {
          background: rgba(239, 83, 80, 0.15);
          color: var(--status-error);
          border-color: var(--status-error);
        }
      `}</style>
    </div>
  )
}
