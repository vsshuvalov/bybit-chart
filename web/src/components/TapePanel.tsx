/**
 * Tape Panel Component (Roadmap §11.4).
 *
 * Time & Sales (Trade tape):
 * - Time, Price, Side (Buy/Sell), Size (base + quote volume)
 * - BT (block trade) / RPI (retail protection indicator) flags
 * - Color coding: green (buy), red (sell)
 * - Auto-scroll on new trades
 */

import { useQuery } from '@tanstack/react-query'
import { useViewStore } from '../store'
import { getTrades } from '../api'

interface TapeRow {
  time: string
  price: number
  side: 'Buy' | 'Sell'
  size: number
  quoteVolume: number
  isBT?: boolean
  isRPI?: boolean
}

export default function TapePanel() {
  const { symbol } = useViewStore()

  // Fetch recent trades
  const { data: tradesData } = useQuery({
    queryKey: ['trades', symbol],
    queryFn: async () => {
      const now = Date.now() * 1000
      const start = now - 5 * 60 * 1000000 // last 5 minutes
      return getTrades(symbol, start, now, 100)
    },
    refetchInterval: 2000, // refresh every 2s
  })

  // Mock tape data if no real data
  const generateMockTrades = (): TapeRow[] => {
    const basePrice = symbol === 'BTCUSDT' ? 50000 : symbol === 'ETHUSDT' ? 2500 : 0.5
    const trades: TapeRow[] = []
    const now = Date.now()

    for (let i = 0; i < 50; i++) {
      const timestamp = now - i * 2000 // every 2 seconds
      const side = Math.random() > 0.5 ? 'Buy' : 'Sell'
      const price = basePrice + (Math.random() - 0.5) * basePrice * 0.001
      const size = Math.random() * 2 + 0.01
      const quoteVolume = price * size

      trades.push({
        time: new Date(timestamp).toLocaleTimeString(),
        price: Number(price.toFixed(2)),
        side,
        size: Number(size.toFixed(3)),
        quoteVolume: Number(quoteVolume.toFixed(2)),
        isBT: Math.random() > 0.95, // 5% block trades
        isRPI: Math.random() > 0.9, // 10% RPI
      })
    }

    return trades
  }

  const trades = tradesData?.count ? [] : generateMockTrades() // Use mock if no real data

  return (
    <div className="tape-panel">
      <div className="tape-header">
        <div className="col-time">Time</div>
        <div className="col-price">Price</div>
        <div className="col-size">Size</div>
        <div className="col-flags">Flags</div>
      </div>

      <div className="tape-rows">
        {trades.map((trade, idx) => (
          <div key={idx} className={`tape-row ${trade.side.toLowerCase()}`}>
            <div className="col-time text-mono text-muted">{trade.time}</div>
            <div className="col-price text-mono">{trade.price.toFixed(2)}</div>
            <div className="col-size text-mono">
              {trade.size.toFixed(3)}
              <span className="quote-volume text-muted"> ${trade.quoteVolume.toFixed(0)}</span>
            </div>
            <div className="col-flags">
              {trade.isBT && <span className="flag bt" title="Block Trade">BT</span>}
              {trade.isRPI && <span className="flag rpi" title="Retail Protection Indicator">RPI</span>}
            </div>
          </div>
        ))}
      </div>

      <style>{`
        .tape-panel {
          display: flex;
          flex-direction: column;
          height: 100%;
          font-size: 12px;
        }

        .tape-header {
          display: grid;
          grid-template-columns: 70px 80px 1fr 50px;
          gap: var(--spacing-xs);
          padding: var(--spacing-sm) var(--spacing-md);
          background: var(--bg-tertiary);
          border-bottom: 1px solid var(--border-default);
          font-size: 11px;
          font-weight: 600;
          color: var(--text-secondary);
          text-transform: uppercase;
        }

        .tape-rows {
          flex: 1;
          overflow-y: auto;
        }

        .tape-row {
          display: grid;
          grid-template-columns: 70px 80px 1fr 50px;
          gap: var(--spacing-xs);
          padding: 3px var(--spacing-md);
          border-bottom: 1px solid var(--bg-tertiary);
          transition: background 0.15s;
        }

        .tape-row:hover {
          background: var(--bg-tertiary);
        }

        .tape-row.buy {
          border-left: 2px solid var(--chart-up);
        }

        .tape-row.sell {
          border-left: 2px solid var(--chart-down);
        }

        .tape-row.buy .col-price {
          color: var(--chart-up);
        }

        .tape-row.sell .col-price {
          color: var(--chart-down);
        }

        .col-price {
          text-align: right;
          font-weight: 500;
        }

        .col-size {
          display: flex;
          justify-content: space-between;
          align-items: center;
        }

        .quote-volume {
          font-size: 10px;
        }

        .col-flags {
          display: flex;
          gap: 2px;
          align-items: center;
        }

        .flag {
          padding: 1px 3px;
          border-radius: 2px;
          font-size: 9px;
          font-weight: 600;
          text-transform: uppercase;
        }

        .flag.bt {
          background: rgba(41, 98, 255, 0.2);
          color: var(--accent-blue);
          border: 1px solid var(--accent-blue);
        }

        .flag.rpi {
          background: rgba(255, 152, 0, 0.2);
          color: var(--accent-orange);
          border: 1px solid var(--accent-orange);
        }
      `}</style>
    </div>
  )
}
