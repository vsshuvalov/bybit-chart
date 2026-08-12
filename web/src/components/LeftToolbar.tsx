/**
 * LeftToolbar Component (Roadmap §11.3).
 *
 * Drawing tools:
 * - Cursor/crosshair
 * - Trend line, ray, extended line
 * - Horizontal/vertical line
 * - Rectangle, ellipse, text/note
 * - Parallel channel
 * - Fibonacci retracement
 * - Anchored VWAP
 * - Fixed-range Volume Profile
 * - Ruler: price/time/percent/ticks/bps
 * - Long/Short risk-reward tool с Entry/SL/TP1–3
 * - Magnet/snap to OHLC/levels
 * - Lock/hide/delete selected; clear drawings с подтверждением
 */

import { useUIStore } from '../store'

type DrawingTool =
  | 'cursor'
  | 'trendline'
  | 'ray'
  | 'horizontal'
  | 'vertical'
  | 'rectangle'
  | 'ellipse'
  | 'text'
  | 'channel'
  | 'fibonacci'
  | 'anchored-vwap'
  | 'volume-profile'
  | 'ruler'
  | 'risk-reward'

const tools: { id: DrawingTool; label: string; icon: string }[] = [
  { id: 'cursor', label: 'Cursor', icon: '↖' },
  { id: 'trendline', label: 'Trend Line', icon: '/' },
  { id: 'ray', label: 'Ray', icon: '→' },
  { id: 'horizontal', label: 'Horizontal', icon: '—' },
  { id: 'vertical', label: 'Vertical', icon: '|' },
  { id: 'rectangle', label: 'Rectangle', icon: '▭' },
  { id: 'ellipse', label: 'Ellipse', icon: '◯' },
  { id: 'text', label: 'Text', icon: 'T' },
  { id: 'channel', label: 'Channel', icon: '‖' },
  { id: 'fibonacci', label: 'Fibonacci', icon: 'φ' },
  { id: 'anchored-vwap', label: 'Anchored VWAP', icon: 'V' },
  { id: 'volume-profile', label: 'Volume Profile', icon: '▬' },
  { id: 'ruler', label: 'Ruler', icon: '📏' },
  { id: 'risk-reward', label: 'Risk/Reward', icon: '⚖' },
]

export default function LeftToolbar() {
  const { activeTool, setActiveTool } = useUIStore()

  return (
    <div className="left-toolbar">
      <div className="toolbar-tools">
        {tools.map((tool) => (
          <button
            key={tool.id}
            className={`tool-btn ${activeTool === tool.id ? 'active' : ''}`}
            onClick={() => setActiveTool(activeTool === tool.id ? null : tool.id)}
            title={tool.label}
          >
            <span className="tool-icon">{tool.icon}</span>
          </button>
        ))}
      </div>

      <div className="toolbar-actions">
        <button className="action-btn" title="Lock selected">
          🔒
        </button>
        <button className="action-btn" title="Hide selected">
          👁
        </button>
        <button className="action-btn danger" title="Delete selected">
          🗑
        </button>
        <button className="action-btn danger" title="Clear all drawings">
          ⚠️
        </button>
      </div>

      <style>{`
        .left-toolbar {
          width: 56px;
          background: var(--bg-secondary);
          border-right: 1px solid var(--border-default);
          display: flex;
          flex-direction: column;
          padding: var(--spacing-sm) 0;
        }

        .toolbar-tools {
          display: flex;
          flex-direction: column;
          gap: 4px;
          padding: 0 var(--spacing-sm);
          flex: 1;
        }

        .toolbar-actions {
          display: flex;
          flex-direction: column;
          gap: 4px;
          padding: var(--spacing-sm);
          border-top: 1px solid var(--border-default);
          margin-top: var(--spacing-sm);
        }

        .tool-btn,
        .action-btn {
          width: 40px;
          height: 40px;
          background: transparent;
          border: 1px solid transparent;
          border-radius: var(--radius-sm);
          color: var(--text-secondary);
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          transition: all 0.2s;
        }

        .tool-btn:hover,
        .action-btn:hover {
          background: var(--bg-tertiary);
          color: var(--text-primary);
          border-color: var(--border-highlight);
        }

        .tool-btn.active {
          background: var(--accent-blue);
          color: white;
          border-color: var(--accent-blue);
        }

        .tool-icon {
          font-size: 18px;
          font-weight: 500;
        }

        .action-btn.danger:hover {
          background: rgba(239, 83, 80, 0.15);
          color: var(--status-error);
          border-color: var(--status-error);
        }

        .tool-btn:focus,
        .action-btn:focus {
          outline: 2px solid var(--accent-blue);
          outline-offset: 2px;
        }
      `}</style>
    </div>
  )
}
