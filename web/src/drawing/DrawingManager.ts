/**
 * Drawing Manager - Roadmap §11.3.
 *
 * State machine для рисования на графике:
 * - Mouse down → start drawing
 * - Mouse move → update preview
 * - Mouse up → finish drawing
 * - Click → select/deselect
 * - Hit testing для selection
 */

import type { IChartApi, ISeriesApi, MouseEventParams } from 'lightweight-charts'
import { useDrawingStore, DrawingTool, Drawing } from '../store/drawingStore'

export interface DrawingPoint {
  time: number
  price: number
  logicalIndex: number
}

export class DrawingManager {
  private chart: IChartApi
  private series: ISeriesApi<'Candlestick'>
  private currentPoints: DrawingPoint[] = []
  private magnetEnabled = true

  constructor(chart: IChartApi, series: ISeriesApi<'Candlestick'>) {
    this.chart = chart
    this.series = series
    this.setupMouseHandlers()
    this.setupKeyboardHandlers()
  }

  private setupMouseHandlers() {
    this.chart.subscribeClick(this.handleClick.bind(this))
    this.chart.subscribeCrosshairMove(this.handleCrosshairMove.bind(this))
  }

  private setupKeyboardHandlers() {
    window.addEventListener('keydown', (e) => {
      const { deleteSelected, undo, redo, clearSelection } = useDrawingStore.getState()

      if (e.key === 'Delete' || e.key === 'Backspace') {
        deleteSelected()
        e.preventDefault()
      }

      if (e.key === 'Escape') {
        this.cancelDrawing()
        clearSelection()
        e.preventDefault()
      }

      if (e.ctrlKey || e.metaKey) {
        if (e.key === 'z') {
          undo()
          e.preventDefault()
        }
        if (e.key === 'y' || (e.shiftKey && e.key === 'z')) {
          redo()
          e.preventDefault()
        }
      }
    })
  }

  private handleClick(param: MouseEventParams) {
    if (!param.point || !param.time) return

    const price = param.seriesData.get(this.series) as any
    if (!price?.close) return

    const { activeTool, setIsDrawing } = useDrawingStore.getState()

    // Cursor mode - selection only
    if (activeTool === 'cursor') {
      this.handleSelection(param)
      return
    }

    // Drawing mode
    const point: DrawingPoint = {
      time: param.time as number,
      price: this.magnetEnabled ? this.snapToPrice(price) : price.close,
      logicalIndex: param.logical || 0,
    }

    this.currentPoints.push(point)
    setIsDrawing(true)

    // Check if drawing is complete
    if (this.isDrawingComplete(activeTool)) {
      this.finishDrawing()
    }
  }

  private handleCrosshairMove(_param: MouseEventParams) {
    const { isDrawing } = useDrawingStore.getState()

    if (!isDrawing || this.currentPoints.length === 0) return

    // Update preview for current drawing
    // TODO: Update primitive preview
  }

  private handleSelection(param: MouseEventParams) {
    const { selectDrawing, clearSelection } = useDrawingStore.getState()

    // Hit test all drawings
    const clicked = this.hitTest(param)

    // Note: MouseEventParams doesn't have ctrlKey/metaKey
    // Multi-select would require custom event handling
    if (clicked) {
      selectDrawing(clicked.id, false)
    } else {
      clearSelection()
    }
  }

  private hitTest(param: MouseEventParams): Drawing | null {
    const { drawings } = useDrawingStore.getState()

    if (!param.point || !param.time) return null

    // Test each drawing for hit
    for (const drawing of drawings) {
      if (drawing.hidden || drawing.locked) continue

      // TODO: Implement precise hit testing based on drawing type
      // For now, simple distance check
      const hit = this.testDrawingHit(drawing, param)
      if (hit) return drawing
    }

    return null
  }

  private testDrawingHit(_drawing: Drawing, _param: MouseEventParams): boolean {
    // TODO: Implement per-tool hit testing
    // TrendLine: distance to line < threshold
    // Rectangle: inside bounds
    // Text: inside bounding box
    return false
  }

  private snapToPrice(ohlc: { open: number; high: number; low: number; close: number }): number {
    // Snap to nearest OHLC value
    const { close } = ohlc
    const distances = [
      { value: ohlc.open, dist: Math.abs(close - ohlc.open) },
      { value: ohlc.high, dist: Math.abs(close - ohlc.high) },
      { value: ohlc.low, dist: Math.abs(close - ohlc.low) },
      { value: close, dist: 0 },
    ]

    distances.sort((a, b) => a.dist - b.dist)
    return distances[0].value
  }

  private isDrawingComplete(tool: DrawingTool): boolean {
    const pointCount = this.currentPoints.length

    switch (tool) {
      case 'horizontal-line':
      case 'vertical-line':
      case 'text':
        return pointCount >= 1
      case 'trendline':
      case 'ray':
      case 'extended-line':
      case 'rectangle':
      case 'ellipse':
      case 'fibonacci':
      case 'ruler':
      case 'anchored-vwap':
        return pointCount >= 2
      case 'parallel-channel':
        return pointCount >= 3
      case 'risk-reward':
        return pointCount >= 3 // Entry, SL, TP
      case 'volume-profile':
        return pointCount >= 2 // Start, end
      default:
        return false
    }
  }

  private finishDrawing() {
    const { activeTool, setIsDrawing, setActiveTool } = useDrawingStore.getState()

    // Create drawing record (primitive will be created later by primitive factory)
    console.log('[DrawingManager] Finished drawing:', activeTool, this.currentPoints)

    // Reset state
    this.currentPoints = []
    setIsDrawing(false)

    // Return to cursor after drawing (TradingView behavior)
    setActiveTool('cursor')
  }

  private cancelDrawing() {
    const { setIsDrawing } = useDrawingStore.getState()
    this.currentPoints = []
    setIsDrawing(false)
  }

  public setMagnetEnabled(enabled: boolean) {
    this.magnetEnabled = enabled
  }

  public destroy() {
    // Cleanup
    window.removeEventListener('keydown', this.setupKeyboardHandlers)
  }
}
