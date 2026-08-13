/**
 * CVD Chart Component (Panel Mode).
 *
 * Lightweight-charts mini-chart showing CVD as line chart.
 */

import { useEffect, useRef } from 'react'
import { createChart, IChartApi, ISeriesApi, LineData } from 'lightweight-charts'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import { useViewStore } from '../store'

interface Trade {
  timestampUs: number
  takerSide: 'Buy' | 'Sell'
  qtySteps: number
}

export default function CVDChart() {
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const { symbol } = useViewStore()

  // Fetch trades
  const { data: tradesData } = useQuery({
    queryKey: ['trades', symbol, { limit: 1000, type: 'cvd' }],
    queryFn: async () => {
      const response = await apiClient.get('/trades', {
        params: { symbol, limit: 1000 },
      })
      return response.data
    },
    refetchInterval: 5000,
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

    const series = chart.addLineSeries({
      color: '#26a69a',
      lineWidth: 2,
      title: 'CVD',
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

    seriesRef.current.setData(cvdData)
    chartRef.current?.timeScale().fitContent()
  }, [tradesData])

  return <div ref={chartContainerRef} style={{ width: '100%', height: '100%' }} />
}
