/**
 * Drawing Store (Zustand) - Roadmap §11.3.
 *
 * Manages drawing state, active tool, selection, undo/redo.
 */

import { create } from 'zustand'
import type { ISeriesPrimitive } from 'lightweight-charts'

export type DrawingTool =
  | 'cursor'
  | 'trendline'
  | 'ray'
  | 'extended-line'
  | 'horizontal-line'
  | 'vertical-line'
  | 'rectangle'
  | 'ellipse'
  | 'text'
  | 'parallel-channel'
  | 'fibonacci'
  | 'anchored-vwap'
  | 'volume-profile'
  | 'ruler'
  | 'risk-reward'

export interface Drawing {
  id: string
  tool: DrawingTool
  primitive: ISeriesPrimitive<any>
  points: Array<{ time: number; price: number }>
  properties: Record<string, any>
  locked: boolean
  hidden: boolean
  createdAt: number
  workspaceId?: string
  symbol?: string
  timeframe?: string
}

interface DrawingState {
  activeTool: DrawingTool
  drawings: Drawing[]
  selectedIds: string[]
  isDrawing: boolean
  undoStack: string[]
  redoStack: string[]

  // Actions
  setActiveTool: (tool: DrawingTool) => void
  addDrawing: (drawing: Drawing) => void
  removeDrawing: (id: string) => void
  updateDrawing: (id: string, updates: Partial<Drawing>) => void
  selectDrawing: (id: string, multi?: boolean) => void
  clearSelection: () => void
  deleteSelected: () => void
  lockSelected: () => void
  hideSelected: () => void
  clearAllDrawings: () => void
  setIsDrawing: (isDrawing: boolean) => void
  undo: () => void
  redo: () => void
}

export const useDrawingStore = create<DrawingState>((set, get) => ({
  activeTool: 'cursor',
  drawings: [],
  selectedIds: [],
  isDrawing: false,
  undoStack: [],
  redoStack: [],

  setActiveTool: (tool) => set({ activeTool: tool, selectedIds: [] }),

  addDrawing: (drawing) =>
    set((state) => ({
      drawings: [...state.drawings, drawing],
      undoStack: [...state.undoStack, `add:${drawing.id}`],
      redoStack: [],
    })),

  removeDrawing: (id) =>
    set((state) => ({
      drawings: state.drawings.filter((d) => d.id !== id),
      selectedIds: state.selectedIds.filter((sid) => sid !== id),
      undoStack: [...state.undoStack, `remove:${id}`],
      redoStack: [],
    })),

  updateDrawing: (id, updates) =>
    set((state) => ({
      drawings: state.drawings.map((d) => (d.id === id ? { ...d, ...updates } : d)),
      undoStack: [...state.undoStack, `update:${id}`],
      redoStack: [],
    })),

  selectDrawing: (id, multi = false) =>
    set((state) => ({
      selectedIds: multi ? [...state.selectedIds, id] : [id],
    })),

  clearSelection: () => set({ selectedIds: [] }),

  deleteSelected: () => {
    const { selectedIds } = get()
    set((state) => ({
      drawings: state.drawings.filter((d) => !selectedIds.includes(d.id)),
      selectedIds: [],
      undoStack: [...state.undoStack, `delete:${selectedIds.join(',')}`],
      redoStack: [],
    }))
  },

  lockSelected: () => {
    const { selectedIds } = get()
    set((state) => ({
      drawings: state.drawings.map((d) =>
        selectedIds.includes(d.id) ? { ...d, locked: true } : d
      ),
    }))
  },

  hideSelected: () => {
    const { selectedIds } = get()
    set((state) => ({
      drawings: state.drawings.map((d) =>
        selectedIds.includes(d.id) ? { ...d, hidden: true } : d
      ),
    }))
  },

  clearAllDrawings: () =>
    set((state) => ({
      drawings: [],
      selectedIds: [],
      undoStack: [...state.undoStack, 'clear-all'],
      redoStack: [],
    })),

  setIsDrawing: (isDrawing) => set({ isDrawing }),

  undo: () => {
    const { undoStack } = get()
    if (undoStack.length === 0) return

    const lastAction = undoStack[undoStack.length - 1]
    // TODO: Implement undo logic based on action type
    set((state) => ({
      undoStack: state.undoStack.slice(0, -1),
      redoStack: [...state.redoStack, lastAction],
    }))
  },

  redo: () => {
    const { redoStack } = get()
    if (redoStack.length === 0) return

    const lastAction = redoStack[redoStack.length - 1]
    // TODO: Implement redo logic based on action type
    set((state) => ({
      redoStack: state.redoStack.slice(0, -1),
      undoStack: [...state.undoStack, lastAction],
    }))
  },
}))
