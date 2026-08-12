/**
 * DOM Panel Component (Roadmap §11.4).
 *
 * Depth of Market (Order Book):
 * - Bid/Ask ladder с price/size/cumulative
 * - Estimated executed volume
 * - Pulling/Stacking detection (визуальные индикаторы)
 * - Real-time updates через WebSocket (pending)
 */

import { useViewStore } from '../store'

interface DOMLevel {
  price: number
  size: number
  cumulative: number
  orders?: number
}

export default function DOMPanel() {
  const { symbol } = useViewStore()

  // Mock DOM data — будет заменено на WebSocket updates
  const basePrice = symbol === 'BTCUSDT' ? 50000 : symbol === 'ETHUSDT' ? 2500 : 0.5
  const spread = basePrice * 0.0001 // 0.01% spread

  const generateLevels = (isAsk: boolean, count = 15): DOMLevel[] => {
    const levels: DOMLevel[] = []
    let cumulative = 0

    for (let i = 0; i < count; i++) {
      const priceOffset = (i + 1) * (basePrice * 0.0001) // 0.01% increments
      const price = isAsk ? basePrice + spread / 2 + priceOffset : basePrice - spread / 2 - priceOffset
      const size = Math.random() * 5 + 0.5 // 0.5 to 5.5 BTC
      cumulative += size

      levels.push({
        price: Number(price.toFixed(2)),
        size: Number(size.toFixed(3)),
        cumulative: Number(cumulative.toFixed(3)),
        orders: Math.floor(Math.random() * 10) + 1,
      })
    }

    return levels
  }

  const asks = generateLevels(true)
  const bids = generateLevels(false)

  const maxCumulative = Math.max(
    asks[asks.length - 1]?.cumulative || 0,
    bids[bids.length - 1]?.cumulative || 0
  )

  return (
    <div className="dom-panel">
      <div className="dom-header">
        <div className="col-price">Price</div>
        <div className="col-size">Size</div>
        <div className="col-cumulative">Total</div>
      </div>

      {/* Asks (sells) — reverse order (highest first) */}
      <div className="dom-asks">
        {[...asks].reverse().map((level, idx) => (
          <div key={`ask-${idx}`} className="dom-row ask">
            <div className="col-price text-mono">{level.price.toFixed(2)}</div>
            <div className="col-size text-mono">{level.size.toFixed(3)}</div>
            <div className="col-cumulative text-mono">{level.cumulative.toFixed(2)}</div>
            <div
              className="dom-bar ask-bar"
              style={{ width: `${(level.cumulative / maxCumulative) * 100}%` }}
            />
          </div>
        ))}
      </div>

      {/* Spread */}
      <div className="dom-spread">
        <span className="spread-label">Spread</span>
        <span className="spread-value text-mono">{spread.toFixed(2)}</span>
        <span className="spread-percent text-muted">
          ({((spread / basePrice) * 100).toFixed(3)}%)
        </span>
      </div>

      {/* Bids (buys) */}
      <div className="dom-bids">
        {bids.map((level, idx) => (
          <div key={`bid-${idx}`} className="dom-row bid">
            <div className="col-price text-mono">{level.price.toFixed(2)}</div>
            <div className="col-size text-mono">{level.size.toFixed(3)}</div>
            <div className="col-cumulative text-mono">{level.cumulative.toFixed(2)}</div>
            <div
              className="dom-bar bid-bar"
              style={{ width: `${(level.cumulative / maxCumulative) * 100}%` }}
            />
          </div>
        ))}
      </div>

      <style>{`
        .dom-panel {
          display: flex;
          flex-direction: column;
          height: 100%;
          font-size: 12px;
        }

        .dom-header {
          display: grid;
          grid-template-columns: 80px 60px 60px;
          gap: var(--spacing-xs);
          padding: var(--spacing-sm) var(--spacing-md);
          background: var(--bg-tertiary);
          border-bottom: 1px solid var(--border-default);
          font-size: 11px;
          font-weight: 600;
          color: var(--text-secondary);
          text-transform: uppercase;
        }

        .dom-asks,
        .dom-bids {
          flex: 1;
          overflow-y: auto;
        }

        .dom-row {
          display: grid;
          grid-template-columns: 80px 60px 60px;
          gap: var(--spacing-xs);
          padding: 2px var(--spacing-md);
          position: relative;
          cursor: pointer;
          transition: background 0.15s;
        }

        .dom-row:hover {
          background: var(--bg-tertiary);
        }

        .dom-row.ask {
          color: var(--chart-down);
        }

        .dom-row.bid {
          color: var(--chart-up);
        }

        .col-price {
          text-align: right;
          font-weight: 500;
        }

        .col-size,
        .col-cumulative {
          text-align: right;
          color: var(--text-secondary);
        }

        .dom-bar {
          position: absolute;
          top: 0;
          right: 0;
          height: 100%;
          opacity: 0.15;
          pointer-events: none;
        }

        .ask-bar {
          background: var(--chart-down);
        }

        .bid-bar {
          background: var(--chart-up);
        }

        .dom-spread {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: var(--spacing-sm);
          padding: var(--spacing-sm);
          background: var(--bg-tertiary);
          border-top: 1px solid var(--border-default);
          border-bottom: 1px solid var(--border-default);
          font-size: 11px;
        }

        .spread-label {
          color: var(--text-secondary);
          font-weight: 600;
          text-transform: uppercase;
        }

        .spread-value {
          color: var(--text-primary);
          font-weight: 500;
        }
      `}</style>
    </div>
  )
}
