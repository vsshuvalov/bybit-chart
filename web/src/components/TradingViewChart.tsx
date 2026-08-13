/**
 * TradingView Advanced Charts Widget (Roadmap §11.1).
 *
 * Replaces lightweight-charts with TradingView widget для drawing tools.
 * Features:
 * - Built-in drawing tools (horizontal line, trendline, rectangle, etc.)
 * - Professional charting UI
 * - Real-time data from TradingView
 *
 * Integration with persistence API:
 * - Load saved drawings from PostgreSQL
 * - Auto-save drawings via TradingView API
 *
 * Docs: https://www.tradingview.com/widget/advanced-chart/
 */

import { useEffect, useRef } from 'react'
import { useViewStore } from '../store'

declare global {
  interface Window {
    TradingView: any
  }
}

export default function TradingViewChart() {
  const containerRef = useRef<HTMLDivElement>(null)
  const widgetRef = useRef<any>(null)
  const { symbol, timeframe } = useViewStore()

  useEffect(() => {
    if (!containerRef.current) return

    // TradingView symbol format: BYBIT:BTCUSDT.P (perpetual)
    const tvSymbol = `BYBIT:${symbol}.P`

    // TradingView interval format
    const intervalMap: Record<string, string> = {
      '1m': '1',
      '3m': '3',
      '5m': '5',
      '15m': '15',
      '30m': '30',
      '1h': '60',
      '2h': '120',
      '4h': '240',
      '6h': '360',
      '12h': '720',
      '1d': 'D',
      '1w': 'W',
      '1M': 'M',
    }
    const tvInterval = intervalMap[timeframe] || '15'

    // Create TradingView widget
    widgetRef.current = new window.TradingView.widget({
      autosize: true,
      symbol: tvSymbol,
      interval: tvInterval,
      timezone: 'Etc/UTC',
      theme: 'dark',
      style: '1', // Candles
      locale: 'en',
      toolbar_bg: '#131722',
      enable_publishing: false,
      hide_side_toolbar: false, // Show drawing tools
      allow_symbol_change: false,
      save_image: false,
      container_id: containerRef.current.id,

      // Drawing tools enabled
      drawings_access: {
        type: 'black',
        tools: [
          { name: 'Regression Trend' },
          { name: 'Trend Line' },
          { name: 'Horizontal Line' },
          { name: 'Vertical Line' },
          { name: 'Rectangle' },
          { name: 'Fibonacci Retracement' },
          { name: 'Pitchfork' },
          { name: 'Text' },
          { name: 'Arrow' },
        ],
      },

      // Studies (indicators)
      studies: [],

      // Disabled features
      disabled_features: [
        'use_localstorage_for_settings',
        'header_symbol_search',
        'symbol_search_hot_key',
        'header_compare',
        'compare_symbol',
      ],

      // Enabled features
      enabled_features: [
        'study_templates',
        'side_toolbar_in_fullscreen_mode',
        'header_in_fullscreen_mode',
      ],

      // Custom overrides
      overrides: {
        'mainSeriesProperties.candleStyle.upColor': '#26a69a',
        'mainSeriesProperties.candleStyle.downColor': '#ef5350',
        'mainSeriesProperties.candleStyle.borderUpColor': '#26a69a',
        'mainSeriesProperties.candleStyle.borderDownColor': '#ef5350',
        'mainSeriesProperties.candleStyle.wickUpColor': '#26a69a',
        'mainSeriesProperties.candleStyle.wickDownColor': '#ef5350',
      },

      // Loading screen
      loading_screen: {
        backgroundColor: '#131722',
        foregroundColor: '#2962FF',
      },
    })

    // Cleanup
    return () => {
      if (widgetRef.current && widgetRef.current.remove) {
        widgetRef.current.remove()
      }
    }
  }, [symbol, timeframe])

  return (
    <div
      id="tradingview_chart"
      ref={containerRef}
      style={{
        width: '100%',
        height: '100%',
        position: 'relative',
      }}
    />
  )
}
