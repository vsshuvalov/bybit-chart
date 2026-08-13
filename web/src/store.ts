/**
 * Global application state with Zustand.
 *
 * State boundaries (Roadmap §11.7):
 * - Market data store: не очищается при unmount/TF change
 * - View store: только представление (symbol, timeframe, viewport)
 * - Execution store: server-confirmed state (positions, orders)
 */

import { create } from 'zustand'

// ----- View State -----

export type Timeframe = '1m' | '5m' | '15m' | '30m' | '1h' | '4h' | '1d'
export type Environment = 'OFFLINE' | 'DEMO' | 'TESTNET' | 'LIVE'
export type TradingState = 'Enabled' | 'SafeMode' | 'Halted'

interface ViewState {
  symbol: string
  timeframe: Timeframe
  environment: Environment
  tradingState: TradingState
  isReplayMode: boolean

  // Actions
  setSymbol: (symbol: string) => void
  setTimeframe: (tf: Timeframe) => void
  setEnvironment: (env: Environment) => void
  setTradingState: (state: TradingState) => void
  toggleReplayMode: () => void
}

export const useViewStore = create<ViewState>((set) => ({
  symbol: 'BTCUSDT',
  timeframe: '15m',
  environment: 'OFFLINE',
  tradingState: 'SafeMode',
  isReplayMode: false,

  setSymbol: (symbol) => set({ symbol }),
  setTimeframe: (timeframe) => set({ timeframe }),
  setEnvironment: (environment) => set({ environment }),
  setTradingState: (tradingState) => set({ tradingState }),
  toggleReplayMode: () => set((state) => ({ isReplayMode: !state.isReplayMode })),
}))

// ----- Market Data Store -----

export interface Tick {
  time: number
  price: number
  volume?: number
  side?: 'Buy' | 'Sell'
}

interface MarketDataState {
  // OHLC data per symbol+timeframe
  ohlcData: Map<string, { timestamp: number; candles: any[] }>

  // Latest trades
  recentTrades: Map<string, Tick[]>

  // Mark prices
  markPrices: Map<string, number>

  // Actions
  setOHLCData: (symbol: string, tf: Timeframe, data: any[]) => void
  addTrade: (symbol: string, trade: Tick) => void
  setMarkPrice: (symbol: string, price: number) => void
  clearSymbolData: (symbol: string) => void
}

export const useMarketDataStore = create<MarketDataState>((set) => ({
  ohlcData: new Map(),
  recentTrades: new Map(),
  markPrices: new Map(),

  setOHLCData: (symbol, tf, candles) =>
    set((state) => {
      const key = `${symbol}_${tf}`
      const newMap = new Map(state.ohlcData)
      newMap.set(key, { timestamp: Date.now(), candles })
      return { ohlcData: newMap }
    }),

  addTrade: (symbol, trade) =>
    set((state) => {
      const newMap = new Map(state.recentTrades)
      const existing = newMap.get(symbol) || []
      // Keep last 100 trades
      const updated = [...existing, trade].slice(-100)
      newMap.set(symbol, updated)
      return { recentTrades: newMap }
    }),

  setMarkPrice: (symbol, price) =>
    set((state) => {
      const newMap = new Map(state.markPrices)
      newMap.set(symbol, price)
      return { markPrices: newMap }
    }),

  clearSymbolData: (symbol) =>
    set((state) => {
      const newOHLC = new Map(state.ohlcData)
      const newTrades = new Map(state.recentTrades)
      const newPrices = new Map(state.markPrices)

      // Remove all keys for this symbol
      for (const key of newOHLC.keys()) {
        if (key.startsWith(symbol + '_')) {
          newOHLC.delete(key)
        }
      }
      newTrades.delete(symbol)
      newPrices.delete(symbol)

      return { ohlcData: newOHLC, recentTrades: newTrades, markPrices: newPrices }
    }),
}))

// ----- UI State -----

interface UIState {
  // Layout
  leftToolbarVisible: boolean
  rightSidebarVisible: boolean
  bottomDockVisible: boolean

  // Active panels
  rightSidebarTab: 'watchlist' | 'dom' | 'tape' | 'levels'
  bottomDockTab: 'delta' | 'oi' | 'strategy' | 'replay'

  // Drawing tool
  activeTool:
    | 'cursor'
    | 'trendline'
    | 'ray'
    | 'horizontal'
    | 'vertical'
    | 'rectangle'
    | 'ellipse'
    | 'text'
    | 'channel'
    | 'fibonacci'
    | 'anchored-vwap'
    | 'volume-profile'
    | 'ruler'
    | 'risk-reward'
    | null

  // Actions
  toggleLeftToolbar: () => void
  toggleRightSidebar: () => void
  toggleBottomDock: () => void
  setRightSidebarTab: (tab: UIState['rightSidebarTab']) => void
  setBottomDockTab: (tab: UIState['bottomDockTab']) => void
  setActiveTool: (tool: UIState['activeTool']) => void
}

export const useUIStore = create<UIState>((set) => ({
  leftToolbarVisible: true,
  rightSidebarVisible: true,
  bottomDockVisible: true,
  rightSidebarTab: 'watchlist',
  bottomDockTab: 'delta',
  activeTool: null,

  toggleLeftToolbar: () => set((state) => ({ leftToolbarVisible: !state.leftToolbarVisible })),
  toggleRightSidebar: () => set((state) => ({ rightSidebarVisible: !state.rightSidebarVisible })),
  toggleBottomDock: () => set((state) => ({ bottomDockVisible: !state.bottomDockVisible })),
  setRightSidebarTab: (tab) => set({ rightSidebarTab: tab }),
  setBottomDockTab: (tab) => set({ bottomDockTab: tab }),
  setActiveTool: (tool) => set({ activeTool: tool }),
}))
