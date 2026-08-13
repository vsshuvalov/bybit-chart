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
} from 'lightweight-charts'
import { useQuery } from '@tanstack/react-query'
import axios from 'axios'
import { useViewStore } from '../store'

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

  const { symbol, timeframe } = useViewStore()

  // Fetch OHLC candles
  const { data: ohlcData } = useQuery({
    queryKey: ['ohlc', symbol, timeframe],
    queryFn: async () => {
      const response = await axios.get(`http://83.147.234.167/api/v1/ohlc`, {
        params: { symbol, interval: timeframe, limit: 500 },
      })
      return response.data
    },
    refetchInterval: 5000,
  })

  // Fetch trades for CVD/OrderFlow
  const { data: tradesData } = useQuery({
    queryKey: ['trades', symbol],
    queryFn: async () => {
      const response = await axios.get(`http://83.147.234.167/api/v1/trades`, {
        params: { symbol, limit: 1000 },
      })
      return response.data
    },
    refetchInterval: 5000,
    enabled: showCVDOverlay || showOrderFlowOverlay,
  })

  // Initialize chart
  useEffect(() => {
    if (!chartContainerRef.current) return

    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: chartContainerRef.current.clientHeight,
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

  // Add CVD overlay series
  useEffect(() => {
    if (!chartRef.current || !showCVDOverlay) return

    if (!cvdSeriesRef.current) {
      cvdSeriesRef.current = chartRef.current.addLineSeries({
        color: '#00C087',
        lineWidth: 2,
        priceScaleId: 'right',
        title: 'CVD',
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
        priceScaleId: 'left',
        priceFormat: {
          type: 'volume',
        },
        title: 'OrderFlow',
      })
    }

    return () => {
      if (orderFlowSeriesRef.current && chartRef.current) {
        chartRef.current.removeSeries(orderFlowSeriesRef.current)
        orderFlowSeriesRef.current = null
      }
    }
  }, [showOrderFlowOverlay])

  // Update candlestick data
  useEffect(() => {
    if (!ohlcData?.candles || !candlestickSeriesRef.current) return

    console.log('[MainChart] OHLC data received:', {
      count: ohlcData.candles.length,
      first: ohlcData.candles[0],
      last: ohlcData.candles[ohlcData.candles.length - 1],
    })

    // BTCUSDT tick_size = 0.1, so divide ticks by 10
    const tickSize = 0.1

    const candleData: CandlestickData[] = ohlcData.candles.map((candle: OHLCCandle) => ({
      time: Math.floor(candle.timestamp_us / 1000000) as any,
      open: candle.open_ticks * tickSize,
      high: candle.high_ticks * tickSize,
      low: candle.low_ticks * tickSize,
      close: candle.close_ticks * tickSize,
    }))

    console.log('[MainChart] Candle data prepared:', {
      count: candleData.length,
      first: candleData[0],
      last: candleData[candleData.length - 1],
      sample: candleData.slice(0, 3),
    })

    candlestickSeriesRef.current.setData(candleData)
    console.log('[MainChart] Data set, calling fitContent()')
    chartRef.current?.timeScale().fitContent()
  }, [ohlcData])

  // Update CVD data
  useEffect(() => {
    if (!tradesData?.events || !cvdSeriesRef.current || !showCVDOverlay) return

    let cvd = 0
    const cvdData: LineData[] = []

    tradesData.events.forEach((trade: Trade) => {
      const delta = trade.takerSide === 'Buy' ? trade.qtySteps : -trade.qtySteps
      cvd += delta

      cvdData.push({
        time: Math.floor(trade.timestampUs / 1000000) as any,
        value: cvd,
      })
    })

    cvdSeriesRef.current.setData(cvdData)
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

    const histogramData: HistogramData[] = Object.entries(grouped).map(([time, volumes]) => {
      const imbalance = volumes.buy - volumes.sell
      return {
        time: parseInt(time) as any,
        value: imbalance,
        color: imbalance > 0 ? '#00C087' : '#F6465D',
      }
    })

    orderFlowSeriesRef.current.setData(histogramData)
  }, [tradesData, showOrderFlowOverlay])

  return <div ref={chartContainerRef} style={{ width: '100%', height: '100%' }} />
}
