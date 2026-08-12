/**
 * Watchlist Component (Roadmap §11.4).
 *
 * Стартовые строки: BTCUSDT, ETHUSDT, XRPUSDT
 * Колонки: Last, 24h %, spread, data-quality, open position, unrealized PnL
 * Клик меняет ViewSession, но не перезапускает collector
 */

import { useQuery } from '@tanstack/react-query'
import { useViewStore } from '../store'
import { getSymbols } from '../api'

interface WatchlistItem {
  symbol: string
  last?: number
  change24h?: number
  spread?: number
  quality: 'good' | 'degraded' | 'stale'
  position?: number
  pnl?: number
}

export default function Watchlist() {
  const { symbol: activeSymbol, setSymbol } = useViewStore()

  const { data: symbolsData } = useQuery({
    queryKey: ['symbols'],
    queryFn: getSymbols,
    refetchInterval: 30000, // refresh every 30s
  })

  // Mock data — будет заменено на реальные данные из API
  const watchlistItems: WatchlistItem[] = (symbolsData?.symbols || ['BTCUSDT', 'ETHUSDT', 'XRPUSDT']).map(
    (sym) => ({
      symbol: sym,
      last: sym === 'BTCUSDT' ? 50123.45 : sym === 'ETHUSDT' ? 2456.78 : 0.5234,
      change24h: Math.random() * 10 - 5, // -5% to +5%
      spread: 0.01,
      quality: 'good',
      position: 0,
      pnl: 0,
    })
  )

  return (
    <div className="watchlist">
      <div className="watchlist-header">
        <div className="col-symbol">Symbol</div>
        <div className="col-last">Last</div>
        <div className="col-change">24h %</div>
        <div className="col-quality">Q</div>
      </div>

      <div className="watchlist-items">
        {watchlistItems.map((item) => (
          <button
            key={item.symbol}
            className={`watchlist-row ${activeSymbol === item.symbol ? 'active' : ''}`}
            onClick={() => setSymbol(item.symbol)}
          >
            <div className="col-symbol">{item.symbol.replace('USDT', '')}</div>
            <div className="col-last text-mono">{item.last?.toFixed(2) || '—'}</div>
            <div className={`col-change text-mono ${item.change24h! >= 0 ? 'text-up' : 'text-down'}`}>
              {item.change24h !== undefined ? `${item.change24h >= 0 ? '+' : ''}${item.change24h.toFixed(2)}%` : '—'}
            </div>
            <div className="col-quality">
              <span className={`quality-dot ${item.quality}`} title={item.quality} />
            </div>
          </button>
        ))}
      </div>

      <style>{`
        .watchlist {
          display: flex;
          flex-direction: column;
          height: 100%;
        }

        .watchlist-header {
          display: grid;
          grid-template-columns: 1fr 80px 60px 24px;
          gap: var(--spacing-xs);
          padding: var(--spacing-sm) var(--spacing-md);
          background: var(--bg-tertiary);
          border-bottom: 1px solid var(--border-default);
          font-size: 11px;
          font-weight: 600;
          color: var(--text-secondary);
          text-transform: uppercase;
        }

        .watchlist-items {
          flex: 1;
          overflow-y: auto;
        }

        .watchlist-row {
          display: grid;
          grid-template-columns: 1fr 80px 60px 24px;
          gap: var(--spacing-xs);
          padding: var(--spacing-sm) var(--spacing-md);
          background: transparent;
          border: none;
          border-bottom: 1px solid var(--border-default);
          color: var(--text-primary);
          font-size: 13px;
          cursor: pointer;
          transition: background 0.2s;
          text-align: left;
          width: 100%;
        }

        .watchlist-row:hover {
          background: var(--bg-tertiary);
        }

        .watchlist-row.active {
          background: rgba(41, 98, 255, 0.15);
          border-left: 2px solid var(--accent-blue);
        }

        .col-symbol {
          font-weight: 500;
        }

        .col-last,
        .col-change {
          text-align: right;
        }

        .col-quality {
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .quality-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
        }

        .quality-dot.good {
          background: var(--status-success);
        }

        .quality-dot.degraded {
          background: var(--status-warning);
        }

        .quality-dot.stale {
          background: var(--status-error);
        }

        .watchlist-row:focus {
          outline: 2px solid var(--accent-blue);
          outline-offset: -2px;
        }
      `}</style>
    </div>
  )
}
