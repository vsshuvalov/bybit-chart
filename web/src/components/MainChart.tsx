/**
 * MainChart Component (Roadmap §11 - Lightweight Charts Implementation).
 *
 * Professional chart with candlesticks + overlays + custom drawing primitives.
 * Replaces TradingView widget for full control over drawings and sync.
 *
 * Features:
 * - Candlestick series from Bybit data
 * - CVD as line overlay (optional)
 * - OrderFlow as histogram overlay (optional)
 * - Custom drawing primitives (12 tools)
 * - Time scale sync with sub-panels
 * - TradingView-inspired design (Roadmap §10.1 colors)
 */

import { useEffect, useRef } from 'react'
import {
  createChart,
  IChartApi,
  ISeriesApi,
  CandlestickData,
  LineData,
  HistogramData,
  CrosshairMode,
  UTCTimestamp,
} from 'lightweight-charts'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import { useViewStore, useMarketDataStore } from '../store'
import { useBybitWebSocket } from '../hooks/useBybitWebSocket'

interface OHLCCandle {
  timestamp_us: number
  open_ticks: number
  high_ticks: number
  low_ticks: number
  close_ticks: number
  volume_steps: number
}

interface Trade {
  timestampUs: number
  takerSide: 'Buy' | 'Sell'
  qtySteps: number
  priceTicks: number
}

interface MainChartProps {
  showCVDOverlay?: boolean
  showOrderFlowOverlay?: boolean
}

export default function MainChart({
  showCVDOverlay = false,
  showOrderFlowOverlay = false,
}: MainChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candlestickSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const cvdSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const orderFlowSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null)

  const { symbol, timeframe, isReplayMode } = useViewStore()
  const recentTrades = useMarketDataStore((state) => state.recentTrades.get(symbol) || [])

  // Live mode: Connect to Bybit WebSocket
  useBybitWebSocket(symbol, !isReplayMode)

  // Replay mode: Fetch OHLC candles from database
  const { data: ohlcData } = useQuery({
    queryKey: ['ohlc', symbol, timeframe],
    queryFn: async () => {
      const response = await apiClient.get('/ohlc', {
        params: { symbol, interval: timeframe, limit: 500 },
      })
      return response.data
    },
    refetchInterval: isReplayMode ? 5000 : false, // Only refetch in replay mode
    enabled: isReplayMode, // Only fetch in replay mode
  })

  // Replay mode: Fetch trades for CVD/OrderFlow from database
  const { data: tradesData } = useQuery({
    queryKey: ['trades', symbol, { limit: 1000 }],
    queryFn: async () => {
      const response = await apiClient.get('/trades', {
        params: { symbol, limit: 1000 },
      })
      return response.data
    },
    refetchInterval: isReplayMode ? 5000 : false, // Only refetch in replay mode
    enabled: isReplayMode && (showCVDOverlay || showOrderFlowOverlay), // Only fetch in replay mode
  })

  // Initialize chart
  useEffect(() => {
    console.log('[MainChart] MOUNTING chart component')

    if (!chartContainerRef.current) return

    const container = chartContainerRef.current
    const width = container.clientWidth || 600
    const height = container.clientHeight || 400

    console.log('[MainChart] Creating chart with size:', width, 'x', height)

    const chart = createChart(container, {
      width,
      height,
      layout: {
        background: { color: '#0B0F14' }, // Roadmap §10.1
        textColor: '#E6EDF3',
      },
      grid: {
        vertLines: { color: '#26313C' },
        horzLines: { color: '#26313C' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
      },
      rightPriceScale: {
        borderColor: '#26313C',
      },
      timeScale: {
        borderColor: '#26313C',
        timeVisible: true,
        secondsVisible: false,
      },
    })

    // Add candlestick series
    const candlestickSeries = chart.addCandlestickSeries({
      upColor: '#00C087',
      downColor: '#F6465D',
      borderUpColor: '#00C087',
      borderDownColor: '#F6465D',
      wickUpColor: '#00C087',
      wickDownColor: '#F6465D',
    })

    chartRef.current = chart
    candlestickSeriesRef.current = candlestickSeries

    // Handle resize
    const handleResize = () => {
      if (container && chart) {
        const newWidth = container.clientWidth || 600
        const newHeight = container.clientHeight || 400
        chart.applyOptions({
          width: newWidth,
          height: newHeight,
        })
      }
    }

    // Initial resize after mount
    const resizeTimeout = setTimeout(handleResize, 100)

    window.addEventListener('resize', handleResize)

    return () => {
      clearTimeout(resizeTimeout)
      window.removeEventListener('resize', handleResize)

      // Clear refs before removing chart
      if (chartRef.current === chart) {
        chartRef.current = null
        candlestickSeriesRef.current = null
        cvdSeriesRef.current = null
        orderFlowSeriesRef.current = null
      }

      chart.remove()
    }
  }, [])

  // Add CVD overlay series
  useEffect(() => {
    if (!chartRef.current || !showCVDOverlay) return

    if (!cvdSeriesRef.current) {
      cvdSeriesRef.current = chartRef.current.addLineSeries({
        color: '#00C087',
        lineWidth: 2,
        priceScaleId: 'cvd', // Separate scale for CVD (cumulative qty_steps)
        title: 'CVD',
        priceLineVisible: false,
        lastValueVisible: false,
      })

      // Configure CVD scale margins (overlay above candles)
      chartRef.current.priceScale('cvd').applyOptions({
        scaleMargins: {
          top: 0.70,
          bottom: 0.05,
        },
      })
    }

    return () => {
      if (cvdSeriesRef.current && chartRef.current) {
        chartRef.current.removeSeries(cvdSeriesRef.current)
        cvdSeriesRef.current = null
      }
    }
  }, [showCVDOverlay])

  // Add OrderFlow overlay series
  useEffect(() => {
    if (!chartRef.current || !showOrderFlowOverlay) return

    if (!orderFlowSeriesRef.current) {
      orderFlowSeriesRef.current = chartRef.current.addHistogramSeries({
        priceScaleId: 'orderflow', // Separate scale for OrderFlow
        priceFormat: {
          type: 'volume',
        },
        title: 'OrderFlow',
        priceLineVisible: false,
        lastValueVisible: false,
      })

      // Configure OrderFlow scale margins (overlay below candles)
      chartRef.current.priceScale('orderflow').applyOptions({
        scaleMargins: {
          top: 0.05,
          bottom: 0.75,
        },
      })
    }

    return () => {
      if (orderFlowSeriesRef.current && chartRef.current) {
        chartRef.current.removeSeries(orderFlowSeriesRef.current)
        orderFlowSeriesRef.current = null
      }
    }
  }, [showOrderFlowOverlay])

  // Track fitted symbol/timeframe to avoid repeated fitContent
  const fittedKeyRef = useRef<string | null>(null)

  // Update candlestick data - Live mode: aggregate from trades
  useEffect(() => {
    if (!candlestickSeriesRef.current) return

    // Live mode: build OHLC from recent trades in store
    if (!isReplayMode && recentTrades.length > 0) {
      // Get interval in seconds
      let intervalSeconds = 60 // default 1m

      if (timeframe === '1m') intervalSeconds = 60
      else if (timeframe === '5m') intervalSeconds = 300
      else if (timeframe === '15m') intervalSeconds = 900
      else if (timeframe === '30m') intervalSeconds = 1800
      else if (timeframe === '1h') intervalSeconds = 3600
      else if (timeframe === '4h') intervalSeconds = 14400
      else if (timeframe === '1d') intervalSeconds = 86400

      // Group trades by candle interval
      const candleMap = new Map<number, { open: number; high: number; low: number; close: number; trades: number }>()

      recentTrades.forEach((trade) => {
        const timestamp = Math.floor(trade.time / 1000) // Convert ms to seconds
        const candleTime = Math.floor(timestamp / intervalSeconds) * intervalSeconds

        if (!candleMap.has(candleTime)) {
          candleMap.set(candleTime, {
            open: trade.price,
            high: trade.price,
            low: trade.price,
            close: trade.price,
            trades: 1,
          })
        } else {
          const candle = candleMap.get(candleTime)!
          candle.high = Math.max(candle.high, trade.price)
          candle.low = Math.min(candle.low, trade.price)
          candle.close = trade.price // Last trade in this candle
          candle.trades++
        }
      })

      // Convert to CandlestickData array
      const candleData: CandlestickData[] = Array.from(candleMap.entries())
        .map(([time, candle]) => ({
          time: time as UTCTimestamp,
          open: candle.open,
          high: candle.high,
          low: candle.low,
          close: candle.close,
        }))
        .sort((a, b) => (a.time as number) - (b.time as number))

      if (candleData.length > 0) {
        // Update only the last candle to avoid flickering
        const lastCandle = candleData[candleData.length - 1]
        candlestickSeriesRef.current.update(lastCandle)

        console.log('[MainChart] Live mode: updated candle', lastCandle)
      }

      return
    }

    // Replay mode: use OHLC from database
    if (isReplayMode && ohlcData?.candles && ohlcData.candles.length > 0) {
      // BTCUSDT tick_size = 0.1, so divide ticks by 10
      // TODO: Get tick_size from instrument metadata API
      const tickSize = 0.1

      const candleData: CandlestickData[] = ohlcData.candles
        .map((candle: OHLCCandle) => ({
          time: Math.floor(candle.timestamp_us / 1000000) as UTCTimestamp,
          open: candle.open_ticks * tickSize,
          high: candle.high_ticks * tickSize,
          low: candle.low_ticks * tickSize,
          close: candle.close_ticks * tickSize,
        }))
        .sort((a: CandlestickData, b: CandlestickData) => (a.time as number) - (b.time as number))

      candlestickSeriesRef.current.setData(candleData)

      // Only fitContent on first load or symbol/timeframe change
      const fitKey = `${symbol}:${timeframe}`
      if (fittedKeyRef.current !== fitKey) {
        chartRef.current?.timeScale().fitContent()
        fittedKeyRef.current = fitKey
      }

      console.log('[MainChart] Replay mode: set', candleData.length, 'candles')
    }
  }, [isReplayMode, recentTrades, ohlcData, symbol, timeframe])

  // Update CVD data
  useEffect(() => {
    if (!tradesData?.events || !cvdSeriesRef.current || !showCVDOverlay) return

    // Aggregate delta by second to ensure unique timestamps
    const deltaBySecond = new Map<number, number>()

    tradesData.events.forEach((trade: Trade) => {
      if (!Number.isSafeInteger(trade.timestampUs) || !Number.isFinite(trade.qtySteps)) {
        return
      }

      const second = Math.floor(trade.timestampUs / 1000000)
      const delta = trade.takerSide === 'Buy' ? trade.qtySteps : -trade.qtySteps
      deltaBySecond.set(second, (deltaBySecond.get(second) ?? 0) + delta)
    })

    // Build cumulative CVD with sorted unique timestamps
    let cumulative = 0
    const cvdData: LineData[] = [...deltaBySecond.entries()]
      .sort(([a], [b]) => a - b)
      .map(([time, delta]) => ({
        time: time as any,
        value: (cumulative += delta),
      }))

    if (cvdData.length > 0) {
      cvdSeriesRef.current.setData(cvdData)
    }
  }, [tradesData, showCVDOverlay])

  // Update OrderFlow data
  useEffect(() => {
    if (!tradesData?.events || !orderFlowSeriesRef.current || !showOrderFlowOverlay) return

    // Group by second
    const grouped: Record<number, { buy: number; sell: number }> = {}

    tradesData.events.forEach((trade: Trade) => {
      const time = Math.floor(trade.timestampUs / 1000000)
      if (!grouped[time]) grouped[time] = { buy: 0, sell: 0 }

      if (trade.takerSide === 'Buy') {
        grouped[time].buy += trade.qtySteps
      } else {
        grouped[time].sell += trade.qtySteps
      }
    })

    const histogramData: HistogramData[] = Object.entries(grouped)
      .map(([time, volumes]) => {
        const imbalance = volumes.buy - volumes.sell
        return {
          time: parseInt(time) as any,
          value: imbalance,
          color: imbalance > 0 ? '#00C087' : '#F6465D',
        }
      })
      .sort((a, b) => (a.time as number) - (b.time as number))

    if (histogramData.length > 0) {
      orderFlowSeriesRef.current.setData(histogramData)
    }
  }, [tradesData, showOrderFlowOverlay])

  return <div ref={chartContainerRef} style={{ width: '100%', height: '100%' }} />
}
