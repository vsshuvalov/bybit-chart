/**
 * Module Visualization Store (Roadmap §11.6).
 *
 * Controls how modules (CVD, OrderFlow, Delta) are displayed:
 * - 'overlay': Canvas overlay on top of TradingView
 * - 'panel': Separate panel below chart
 */

import { create } from 'zustand'

export type VisualizationMode = 'overlay' | 'panel'

interface ModuleVisualizationState {
  mode: VisualizationMode
  setMode: (mode: VisualizationMode) => void
}

export const useModuleVisualizationStore = create<ModuleVisualizationState>((set) => ({
  mode: (localStorage.getItem('moduleVisualizationMode') as VisualizationMode) || 'overlay',
  setMode: (mode) => {
    localStorage.setItem('moduleVisualizationMode', mode)
    set({ mode })
  },
}))
