/**
 * OrderFlow Chart Component (Panel Mode).
 *
 * Lightweight-charts histogram showing buy/sell imbalance.
 */

import { useEffect, useRef } from 'react'
import { createChart, IChartApi, ISeriesApi, HistogramData } from 'lightweight-charts'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import { useViewStore } from '../store'

interface Trade {
  timestampUs: number
  takerSide: 'Buy' | 'Sell'
  qtySteps: number
}

export default function OrderFlowChart() {
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const { symbol } = useViewStore()

  // Fetch trades
  const { data: tradesData } = useQuery({
    queryKey: ['trades', symbol, { limit: 500, type: 'orderflow' }],
    queryFn: async () => {
      const response = await apiClient.get('/trades', {
        params: { symbol, limit: 500 },
      })
      return response.data
    },
    refetchInterval: 2000,
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
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
      },
    })

    const series = chart.addHistogramSeries({
      title: 'Imbalance',
    })

    chartRef.current = chart
    seriesRef.current = series

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

  // Update chart data
  useEffect(() => {
    if (!tradesData?.events || !seriesRef.current) return

    // Group trades by second
    const grouped: Record<number, { buy: number; sell: number }> = {}

    tradesData.events.forEach((trade: Trade) => {
      const time = Math.floor(trade.timestampUs / 1000000)
      if (!grouped[time]) {
        grouped[time] = { buy: 0, sell: 0 }
      }

      if (trade.takerSide === 'Buy') {
        grouped[time].buy += trade.qtySteps
      } else {
        grouped[time].sell += trade.qtySteps
      }
    })

    // Convert to histogram data
    const histogramData: HistogramData[] = Object.entries(grouped).map(([time, volumes]) => {
      const imbalance = volumes.buy - volumes.sell
      return {
        time: parseInt(time) as any,
        value: imbalance,
        color: imbalance > 0 ? '#26a69a' : '#ef5350',
      }
    })

    seriesRef.current.setData(histogramData)
    chartRef.current?.timeScale().fitContent()
  }, [tradesData])

  return <div ref={chartContainerRef} style={{ width: '100%', height: '100%' }} />
}
