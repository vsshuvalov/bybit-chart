/**
 * Instrument metadata API client.
 *
 * Fetches tick_size, qty_step, and other instrument specs
 * for accurate price/volume conversion.
 */

import { apiClient } from './client'

export interface InstrumentInfo {
  symbol: string
  tick_size: number
  qty_step: number
  min_qty: number
  max_qty: number
  base_asset: string
  quote_asset: string
}

export interface InstrumentsResponse {
  instruments: InstrumentInfo[]
  count: number
}

/**
 * Get all available instruments with metadata.
 */
export async function getInstruments(): Promise<InstrumentInfo[]> {
  const response = await apiClient.get<InstrumentsResponse>('/instruments')
  return response.data.instruments
}

/**
 * Get metadata for specific instrument.
 */
export async function getInstrument(symbol: string): Promise<InstrumentInfo> {
  const response = await apiClient.get<InstrumentInfo>(`/instruments/${symbol}`)
  return response.data
}

/**
 * Convert price ticks to float price.
 */
export function ticksToPrice(ticks: number, tickSize: number): number {
  return ticks * tickSize
}

/**
 * Convert quantity steps to float quantity.
 */
export function stepsToQty(steps: number, qtyStep: number): number {
  return steps * qtyStep
}
