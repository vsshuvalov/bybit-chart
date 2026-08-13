/**
 * ChartPanel Component (Roadmap §11.1, §11.5).
 *
 * Center panel: price chart с OHLC candles (lightweight-charts).
 * Timeframe switcher уже в TopBar.
 * WS updates для live mode.
 */

import { useEffect, useRef } from 'react'
import { createChart, IChartApi, ISeriesApi, CandlestickData } from 'lightweight-charts'
import { useQuery } from '@tanstack/react-query'
import { useViewStore, useMarketDataStore } from '../store'
import { getOHLC } from '../api'

export default function ChartPanel() {
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const lastCandleRef = useRef<CandlestickData | null>(null)

  const { symbol, timeframe, isReplayMode } = useViewStore()
  const recentTrades = useMarketDataStore((state) => state.recentTrades.get(symbol) || [])

  // Fetch OHLC data - отключаем polling в live mode
  const { data: ohlcData, error } = useQuery({
    queryKey: ['ohlc', symbol, timeframe],
    queryFn: async () => {
      const now = Date.now() * 1000 // microseconds
      const start = now - 24 * 60 * 60 * 1000000 // last 24h
      return getOHLC(symbol, start, now, timeframe)
    },
    refetchInterval: isReplayMode ? 10000 : false, // только в replay mode
  })

  // Mock data fallback if API returns no candles
  const useMockData = !ohlcData || ohlcData.count === 0

  // Initialize chart
  useEffect(() => {
    if (!chartContainerRef.current) return

    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: chartContainerRef.current.clientHeight,
      layout: {
        background: { color: '#131722' },
        textColor: '#d1d4dc',
      },
      grid: {
        vertLines: { color: '#2a2e39' },
        horzLines: { color: '#2a2e39' },
      },
      crosshair: {
        mode: 1, // Normal
      },
      rightPriceScale: {
        borderColor: '#2a2e39',
      },
      timeScale: {
        borderColor: '#2a2e39',
        timeVisible: true,
        secondsVisible: false,
      },
    })

    const candleSeries = chart.addCandlestickSeries({
      upColor: '#26a69a',
      downColor: '#ef5350',
      borderUpColor: '#26a69a',
      borderDownColor: '#ef5350',
      wickUpColor: '#26a69a',
      wickDownColor: '#ef5350',
    })

    chartRef.current = chart
    candleSeriesRef.current = candleSeries

    // Handle resize
    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chart.applyOptions({
          width: chartContainerRef.current.clientWidth,
          height: chartContainerRef.current.clientHeight,
        })
      }
    }

    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
    }
  }, [])

  // Update data when ohlcData changes
  useEffect(() => {
    if (!candleSeriesRef.current) return

    let candles: CandlestickData[] = []

    if (ohlcData && ohlcData.count > 0) {
      // Real data from API
      candles = ohlcData.candles.map((c) => ({
        time: Math.floor(c.timestamp_us / 1000000) as any, // seconds
        open: c.open_ticks / 100, // ticks to price (assuming 0.01 tick size)
        high: c.high_ticks / 100,
        low: c.low_ticks / 100,
        close: c.close_ticks / 100,
      }))
    } else {
      // Mock data for demo (no backend data available)
      const now = Math.floor(Date.now() / 1000)
      const basePrice = symbol === 'BTCUSDT' ? 50000 : symbol === 'ETHUSDT' ? 2500 : 0.5
      const intervalSeconds = timeframe === '1m' ? 60 : timeframe === '5m' ? 300 : timeframe === '15m' ? 900 : 3600

      for (let i = 0; i < 100; i++) {
        const time = now - (100 - i) * intervalSeconds
        const noise = (Math.random() - 0.5) * basePrice * 0.01
        const open = basePrice + noise
        const close = open + (Math.random() - 0.5) * basePrice * 0.005
        const high = Math.max(open, close) + Math.random() * basePrice * 0.003
        const low = Math.min(open, close) - Math.random() * basePrice * 0.003

        candles.push({
          time: time as any,
          open,
          high,
          low,
          close,
        })
      }
    }

    candleSeriesRef.current.setData(candles)

    // Сохраняем последнюю свечу для обновления
    if (candles.length > 0) {
      lastCandleRef.current = candles[candles.length - 1]
    }
  }, [ohlcData, symbol, timeframe, useMockData])

  // 🔥 NEW: Update chart from WebSocket trades in real-time
  useEffect(() => {
    if (!candleSeriesRef.current || !lastCandleRef.current || isReplayMode || recentTrades.length === 0) {
      return
    }

    // Получаем интервал свечи в секундах
    const getIntervalSeconds = () => {
      switch (timeframe) {
        case '1m': return 60
        case '5m': return 300
        case '15m': return 900
        case '30m': return 1800
        case '1h': return 3600
        case '4h': return 14400
        case '1d': return 86400
        default: return 60
      }
    }

    const intervalSeconds = getIntervalSeconds()
    const lastTrade = recentTrades[recentTrades.length - 1]
    const tradeTime = Math.floor(lastTrade.time / 1000) // seconds
    const tradePrice = lastTrade.price / 100 // ticks to price

    // Определяем время текущей свечи
    const currentCandleTime = Math.floor(tradeTime / intervalSeconds) * intervalSeconds
    const lastCandleTime = lastCandleRef.current.time as number

    if (currentCandleTime === lastCandleTime) {
      // Обновляем текущую свечу
      const updatedCandle: CandlestickData = {
        ...lastCandleRef.current,
        high: Math.max(lastCandleRef.current.high, tradePrice),
        low: Math.min(lastCandleRef.current.low, tradePrice),
        close: tradePrice,
      }

      lastCandleRef.current = updatedCandle
      candleSeriesRef.current.update(updatedCandle)

      console.log('[ChartPanel] Updated candle:', updatedCandle)
    } else if (currentCandleTime > lastCandleTime) {
      // Создаём новую свечу
      const newCandle: CandlestickData = {
        time: currentCandleTime as any,
        open: tradePrice,
        high: tradePrice,
        low: tradePrice,
        close: tradePrice,
      }

      lastCandleRef.current = newCandle
      candleSeriesRef.current.update(newCandle)

      console.log('[ChartPanel] New candle:', newCandle)
    }
  }, [recentTrades, timeframe, isReplayMode])

  return (
    <div className="chart-panel">
      <div className="chart-container" ref={chartContainerRef} />

      {useMockData && (
        <div className="mock-data-badge">
          ⚠️ Mock Data (no backend data)
        </div>
      )}

      {!isReplayMode && (
        <div className="live-indicator">
          🔴 LIVE
        </div>
      )}

      {!ohlcData && !error && (
        <div className="chart-loading">
          <div className="loading-spinner" />
          <div>Loading {symbol} {timeframe} data...</div>
        </div>
      )}

      <style>{`
        .chart-panel {
          flex: 1;
          position: relative;
          background: var(--bg-primary);
        }

        .chart-container {
          width: 100%;
          height: 100%;
        }

        .chart-loading {
          position: absolute;
          top: 50%;
          left: 50%;
          transform: translate(-50%, -50%);
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: var(--spacing-md);
          color: var(--text-muted);
          font-size: 14px;
        }

        .loading-spinner {
          width: 32px;
          height: 32px;
          border: 3px solid var(--border-default);
          border-top-color: var(--accent-blue);
          border-radius: 50%;
          animation: spin 1s linear infinite;
        }

        @keyframes spin {
          to {
            transform: rotate(360deg);
          }
        }

        .mock-data-badge {
          position: absolute;
          top: var(--spacing-md);
          right: var(--spacing-md);
          padding: 6px 12px;
          background: rgba(255, 152, 0, 0.15);
          border: 1px solid var(--status-warning);
          border-radius: var(--radius-sm);
          color: var(--status-warning);
          font-size: 12px;
          font-weight: 500;
          z-index: 10;
        }

        .live-indicator {
          position: absolute;
          top: var(--spacing-md);
          left: var(--spacing-md);
          padding: 6px 12px;
          background: rgba(239, 83, 80, 0.15);
          border: 1px solid #ef5350;
          border-radius: var(--radius-sm);
          color: #ef5350;
          font-size: 12px;
          font-weight: 500;
          z-index: 10;
          animation: pulse 2s infinite;
        }

        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.6; }
        }
      `}</style>
    </div>
  )
}
