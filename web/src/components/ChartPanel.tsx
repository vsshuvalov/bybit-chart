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
import { useViewStore } from '../store'
import { getOHLC } from '../api'

export default function ChartPanel() {
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)

  const { symbol, timeframe } = useViewStore()

  // Fetch OHLC data
  const { data: ohlcData } = useQuery({
    queryKey: ['ohlc', symbol, timeframe],
    queryFn: async () => {
      const now = Date.now() * 1000 // microseconds
      const start = now - 24 * 60 * 60 * 1000000 // last 24h
      return getOHLC(symbol, start, now, timeframe)
    },
    refetchInterval: 10000, // refresh every 10s
  })

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
    if (!candleSeriesRef.current || !ohlcData) return

    // Convert API data to lightweight-charts format
    const candles: CandlestickData[] = ohlcData.candles.map((c) => ({
      time: Math.floor(c.timestamp_us / 1000000) as any, // seconds
      open: c.open_ticks / 100, // ticks to price (assuming 0.01 tick size)
      high: c.high_ticks / 100,
      low: c.low_ticks / 100,
      close: c.close_ticks / 100,
    }))

    candleSeriesRef.current.setData(candles)
  }, [ohlcData])

  return (
    <div className="chart-panel">
      <div className="chart-container" ref={chartContainerRef} />

      {!ohlcData && (
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
      `}</style>
    </div>
  )
}
