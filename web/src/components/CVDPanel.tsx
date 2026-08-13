/**
 * CVD Panel Component
 *
 * Показывает Cumulative Volume Delta line chart
 */

import { useEffect, useRef } from 'react'
import { createChart, IChartApi, ISeriesApi } from 'lightweight-charts'
import { useQuery } from '@tanstack/react-query'
import { useViewStore } from '../store'
import { getCVD } from '../api'

export default function CVDPanel() {
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const lineSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)

  const { symbol, timeframe } = useViewStore()

  const { data, error, isLoading } = useQuery({
    queryKey: ['cvd', symbol, timeframe],
    queryFn: () => getCVD(symbol),
    refetchInterval: 10000,
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
        borderColor: '#2a2e39',
        timeVisible: true,
      },
      rightPriceScale: {
        borderColor: '#2a2e39',
      },
    })

    const lineSeries = chart.addLineSeries({
      color: '#2962FF',
      lineWidth: 2,
    })

    chartRef.current = chart
    lineSeriesRef.current = lineSeries

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

  // Update data
  useEffect(() => {
    if (!lineSeriesRef.current || !data || !data.bars) return

    const lineData = data.bars.map((bar: any) => ({
      time: Math.floor(bar.timestamp_us / 1000000) as any,
      value: bar.cvd || 0,
    }))

    lineSeriesRef.current.setData(lineData)
  }, [data])

  if (isLoading) {
    return (
      <div style={{ padding: '16px', color: 'var(--text-muted)' }}>
        Loading CVD data...
      </div>
    )
  }

  if (error) {
    return (
      <div style={{ padding: '16px', color: 'var(--status-error)' }}>
        Error loading CVD data
      </div>
    )
  }

  return <div ref={chartContainerRef} style={{ width: '100%', height: '100%' }} />
}
