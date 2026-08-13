/**
 * API client for Bybit Order Flow Platform.
 *
 * Base URL: /api/v1
 * Proxy configured in vite.config.ts → http://localhost:8000
 */

import axios from 'axios'

const apiClient = axios.create({
  baseURL: '/api/v1',
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Response interceptor for error handling
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error('API Error:', error.response?.data || error.message)
    return Promise.reject(error)
  }
)

export default apiClient

// ----- Types -----

export interface Symbol {
  symbol: string
  last?: number
  change24h?: number
  spread?: number
  quality?: 'good' | 'degraded' | 'stale'
}

export interface TradeEvent {
  eventType: 'RawTrade'
  symbol: string
  timestamp_us: number
  side: 'Buy' | 'Sell'
  price_ticks: number
  qty_steps: number
  sequence: number
}

export interface OHLCCandle {
  timestamp_us: number
  open_ticks: number
  high_ticks: number
  low_ticks: number
  close_ticks: number
  volume_steps: number
}

export interface OHLCResponse {
  symbol: string
  interval: string
  start_ts: number
  end_ts: number
  candles: OHLCCandle[]
  count: number
}

export interface TradesResponse {
  symbol: string
  start_ts: number
  end_ts: number
  events: TradeEvent[]
  count: number
  has_more: boolean
}

// ----- API Functions -----

export const getSymbols = async (): Promise<{ symbols: string[]; count: number }> => {
  const { data } = await apiClient.get('/symbols')
  return data
}

export const getTrades = async (
  symbol: string,
  start_ts: number,
  end_ts: number,
  limit = 1000
): Promise<TradesResponse> => {
  const { data } = await apiClient.get('/trades', {
    params: { symbol, start_ts, end_ts, limit },
  })
  return data
}

export const getOHLC = async (
  symbol: string,
  start_ts: number,
  end_ts: number,
  interval: string
): Promise<OHLCResponse> => {
  console.log('[API] getOHLC request:', { symbol, start_ts, end_ts, interval })
  const { data } = await apiClient.get('/ohlc', {
    params: {
      symbol,
      start_us: start_ts,  // Backend expects start_us, not start_ts
      end_us: end_ts,      // Backend expects end_us, not end_ts
      interval
    },
  })
  console.log('[API] getOHLC response:', data)
  return data
}

export const getDelta = async (symbol: string, interval: string) => {
  const { data } = await apiClient.get('/analytics/delta', {
    params: { symbol, interval },
  })
  return data
}

export const getCVD = async (symbol: string) => {
  const { data } = await apiClient.get('/analytics/cvd', {
    params: { symbol },
  })
  return data
}

export const getVWAP = async (symbol: string, interval: string) => {
  const { data } = await apiClient.get('/analytics/vwap', {
    params: { symbol, interval },
  })
  return data
}

export const getVolumeProfile = async (symbol: string, interval: string) => {
  const { data } = await apiClient.get('/analytics/volume-profile', {
    params: { symbol, interval },
  })
  return data
}

export const getHeatmap = async (symbol: string) => {
  const { data } = await apiClient.get('/analytics/heatmap', {
    params: { symbol },
  })
  return data
}

export const getRegime = async (symbol: string) => {
  const { data } = await apiClient.get('/analytics/orderflow/regime', {
    params: { symbol },
  })
  return data
}

export const getFeatures = async (symbol: string) => {
  const { data } = await apiClient.get('/analytics/orderflow/features', {
    params: { symbol },
  })
  return data
}
