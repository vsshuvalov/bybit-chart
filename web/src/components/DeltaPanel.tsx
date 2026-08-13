/**
 * Delta Panel Component
 *
 * Показывает Buy/Sell volume delta histogram
 */

import { useEffect, useRef } from 'react'
import { createChart, IChartApi, ISeriesApi } from 'lightweight-charts'
import { useQuery } from '@tanstack/react-query'
import { useViewStore } from '../store'
import { getDelta } from '../api'

export default function DeltaPanel() {
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const histogramSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null)

  const { symbol, timeframe } = useViewStore()

  const { data, error, isLoading } = useQuery({
    queryKey: ['delta', symbol, timeframe],
    queryFn: () => getDelta(symbol, timeframe),
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

    const histogramSeries = chart.addHistogramSeries({
      color: '#26a69a',
      priceFormat: {
        type: 'volume',
      },
    })

    chartRef.current = chart
    histogramSeriesRef.current = histogramSeries

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
    if (!histogramSeriesRef.current || !data || !data.bars) return

    const histogramData = data.bars.map((bar: any) => ({
      time: Math.floor(bar.timestamp_us / 1000000) as any,
      value: bar.delta,
      color: bar.delta >= 0 ? '#26a69a' : '#ef5350',
    }))

    histogramSeriesRef.current.setData(histogramData)
  }, [data])

  if (isLoading) {
    return (
      <div style={{ padding: '16px', color: 'var(--text-muted)' }}>
        Loading Delta data...
      </div>
    )
  }

  if (error) {
    return (
      <div style={{ padding: '16px', color: 'var(--status-error)' }}>
        Error loading Delta data
      </div>
    )
  }

  return <div ref={chartContainerRef} style={{ width: '100%', height: '100%' }} />
}
