/**
 * Base Primitive Class for Drawing Tools.
 *
 * All drawing tools (TrendLine, Rectangle, etc.) extend this.
 * Implements ISeriesPrimitive<Time> interface from lightweight-charts.
 */

import type {
  ISeriesPrimitive,
  ISeriesPrimitivePaneView,
  Time,
  PrimitiveHoveredItem,
} from 'lightweight-charts'

export interface DrawingPoint {
  time: number
  price: number
}

export interface BasePrimitiveOptions {
  color?: string
  lineWidth?: number
  lineStyle?: 'solid' | 'dashed' | 'dotted'
  fillColor?: string
  fillOpacity?: number
  text?: string
  fontSize?: number
  locked?: boolean
  hidden?: boolean
}

export abstract class BasePrimitive implements ISeriesPrimitive<Time> {
  protected points: DrawingPoint[]
  protected options: BasePrimitiveOptions
  protected _paneViews: ISeriesPrimitivePaneView[]

  constructor(points: DrawingPoint[], options: BasePrimitiveOptions = {}) {
    this.points = points
    this.options = {
      color: options.color || '#2196F3',
      lineWidth: options.lineWidth || 2,
      lineStyle: options.lineStyle || 'solid',
      fillColor: options.fillColor,
      fillOpacity: options.fillOpacity || 0.2,
      text: options.text,
      fontSize: options.fontSize || 12,
      locked: options.locked || false,
      hidden: options.hidden || false,
    }
    this._paneViews = []
  }

  abstract updateAllViews(): void

  paneViews() {
    return this._paneViews
  }

  updatePoints(points: DrawingPoint[]) {
    this.points = points
    this.updateAllViews()
  }

  updateOptions(options: Partial<BasePrimitiveOptions>) {
    this.options = { ...this.options, ...options }
    this.updateAllViews()
  }

  getPoints(): DrawingPoint[] {
    return this.points
  }

  getOptions(): BasePrimitiveOptions {
    return this.options
  }

  hitTest(): PrimitiveHoveredItem | null {
    // Default hit test - override in subclasses
    return null
  }
}

// Pane View Renderer Base Class
export abstract class BasePaneRenderer {
  protected _data: any

  setData(data: any) {
    this._data = data
  }

  abstract draw(target: CanvasRenderingContext2D): void
}

// Helper: Convert line style to canvas dash pattern
export function getLineDash(style: 'solid' | 'dashed' | 'dotted'): number[] {
  switch (style) {
    case 'dashed':
      return [6, 3]
    case 'dotted':
      return [2, 2]
    default:
      return []
  }
}

// Helper: Distance from point to line segment
export function distanceToLineSegment(
  px: number,
  py: number,
  x1: number,
  y1: number,
  x2: number,
  y2: number
): number {
  const A = px - x1
  const B = py - y1
  const C = x2 - x1
  const D = y2 - y1

  const dot = A * C + B * D
  const lenSq = C * C + D * D
  let param = -1

  if (lenSq !== 0) param = dot / lenSq

  let xx, yy

  if (param < 0) {
    xx = x1
    yy = y1
  } else if (param > 1) {
    xx = x2
    yy = y2
  } else {
    xx = x1 + param * C
    yy = y1 + param * D
  }

  const dx = px - xx
  const dy = py - yy

  return Math.sqrt(dx * dx + dy * dy)
}

// Helper: Check if point is inside rectangle
export function isPointInRect(
  px: number,
  py: number,
  x1: number,
  y1: number,
  x2: number,
  y2: number
): boolean {
  const minX = Math.min(x1, x2)
  const maxX = Math.max(x1, x2)
  const minY = Math.min(y1, y2)
  const maxY = Math.max(y1, y2)

  return px >= minX && px <= maxX && py >= minY && py <= maxY
}
