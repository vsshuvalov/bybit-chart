/**
 * Frontend API client для Drawings и Workspaces (Roadmap §11.3, §11.7).
 *
 * Server persistence (NOT localStorage).
 * TypeScript types aligned с backend Pydantic models.
 */

import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// ========== Types (aligned с backend) ==========

export interface DrawingPoint {
  timestamp_us: number
  price_ticks: number
}

export type DrawingType =
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

export interface Drawing {
  id: string // UUID
  type: DrawingType
  symbol: string
  points: DrawingPoint[]
  style: Record<string, any>
  locked: boolean
  hidden: boolean
  created_at: string // ISO 8601
  updated_at: string // ISO 8601
}

export interface DrawingListResponse {
  symbol: string
  drawings: Drawing[]
  count: number
}

export interface CreateDrawingRequest {
  type: DrawingType
  symbol: string
  points: DrawingPoint[]
  style?: Record<string, any>
}

export interface UpdateDrawingRequest {
  points?: DrawingPoint[]
  style?: Record<string, any>
  locked?: boolean
  hidden?: boolean
}

export interface Workspace {
  id: string // UUID
  name: string
  symbol: string
  timeframe: string
  layout: Record<string, any>
  indicators: Array<Record<string, any>>
  drawing_ids: string[]
  created_at: string
  updated_at: string
}

export interface WorkspaceListResponse {
  workspaces: Workspace[]
  count: number
}

export interface CreateWorkspaceRequest {
  name: string
  symbol: string
  timeframe: string
  layout?: Record<string, any>
  indicators?: Array<Record<string, any>>
  drawing_ids?: string[]
}

export interface UpdateWorkspaceRequest {
  name?: string
  symbol?: string
  timeframe?: string
  layout?: Record<string, any>
  indicators?: Array<Record<string, any>>
  drawing_ids?: string[]
}

// ========== Drawings API ==========

/**
 * List drawings for symbol.
 *
 * Roadmap §11.3: Server source of truth.
 */
export async function listDrawings(
  symbol: string,
  includeHidden = false,
  workspaceId?: string
): Promise<DrawingListResponse> {
  const params = new URLSearchParams({ symbol, include_hidden: String(includeHidden) })
  if (workspaceId) params.set('workspace_id', workspaceId)

  const response = await axios.get<DrawingListResponse>(`${API_BASE}/api/v1/drawings`, { params })
  return response.data
}

/**
 * Create drawing.
 *
 * Roadmap §11.3: schemaVersion tracking, server persistence.
 */
export async function createDrawing(request: CreateDrawingRequest): Promise<Drawing> {
  const response = await axios.post<Drawing>(`${API_BASE}/api/v1/drawings`, request)
  return response.data
}

/**
 * Get drawing by ID.
 */
export async function getDrawing(drawingId: string): Promise<Drawing> {
  const response = await axios.get<Drawing>(`${API_BASE}/api/v1/drawings/${drawingId}`)
  return response.data
}

/**
 * Update drawing.
 *
 * Roadmap §11.3: Increments revision counter.
 */
export async function updateDrawing(
  drawingId: string,
  request: UpdateDrawingRequest
): Promise<Drawing> {
  const response = await axios.put<Drawing>(`${API_BASE}/api/v1/drawings/${drawingId}`, request)
  return response.data
}

/**
 * Delete drawing permanently.
 */
export async function deleteDrawing(drawingId: string): Promise<void> {
  await axios.delete(`${API_BASE}/api/v1/drawings/${drawingId}`)
}

// ========== Workspaces API ==========

/**
 * List workspaces.
 *
 * Roadmap §11.7: Server persistence, localStorage only for UI cache.
 */
export async function listWorkspaces(author?: string): Promise<WorkspaceListResponse> {
  const params = author ? { author } : undefined
  const response = await axios.get<WorkspaceListResponse>(`${API_BASE}/api/v1/workspaces`, {
    params,
  })
  return response.data
}

/**
 * Create workspace.
 *
 * Roadmap §11.2: Open, save, create copy, export/import.
 */
export async function createWorkspace(request: CreateWorkspaceRequest): Promise<Workspace> {
  const response = await axios.post<Workspace>(`${API_BASE}/api/v1/workspaces`, request)
  return response.data
}

/**
 * Get workspace by ID.
 */
export async function getWorkspace(workspaceId: string): Promise<Workspace> {
  const response = await axios.get<Workspace>(`${API_BASE}/api/v1/workspaces/${workspaceId}`)
  return response.data
}

/**
 * Update workspace.
 *
 * Roadmap §11.7: Increments revision counter.
 */
export async function updateWorkspace(
  workspaceId: string,
  request: UpdateWorkspaceRequest
): Promise<Workspace> {
  const response = await axios.put<Workspace>(
    `${API_BASE}/api/v1/workspaces/${workspaceId}`,
    request
  )
  return response.data
}

/**
 * Delete workspace permanently.
 */
export async function deleteWorkspace(workspaceId: string): Promise<void> {
  await axios.delete(`${API_BASE}/api/v1/workspaces/${workspaceId}`)
}

/**
 * Get drawings associated with workspace.
 */
export async function getWorkspaceDrawings(workspaceId: string): Promise<DrawingListResponse> {
  const response = await axios.get<DrawingListResponse>(
    `${API_BASE}/api/v1/workspaces/${workspaceId}/drawings`
  )
  return response.data
}

// ========== Helper Functions ==========

/**
 * Auto-save drawing (debounced).
 *
 * Call this on every drawing update to persist to server.
 */
let saveTimeout: NodeJS.Timeout | null = null
export function autoSaveDrawing(drawingId: string, updates: UpdateDrawingRequest, delay = 500) {
  if (saveTimeout) clearTimeout(saveTimeout)
  saveTimeout = setTimeout(async () => {
    try {
      await updateDrawing(drawingId, updates)
      console.log('[Persistence] Drawing auto-saved:', drawingId)
    } catch (error) {
      console.error('[Persistence] Drawing auto-save failed:', error)
    }
  }, delay)
}

/**
 * Auto-save workspace (debounced).
 *
 * Call this on layout/indicator changes to persist to server.
 */
let workspaceSaveTimeout: NodeJS.Timeout | null = null
export function autoSaveWorkspace(
  workspaceId: string,
  updates: UpdateWorkspaceRequest,
  delay = 1000
) {
  if (workspaceSaveTimeout) clearTimeout(workspaceSaveTimeout)
  workspaceSaveTimeout = setTimeout(async () => {
    try {
      await updateWorkspace(workspaceId, updates)
      console.log('[Persistence] Workspace auto-saved:', workspaceId)
    } catch (error) {
      console.error('[Persistence] Workspace auto-save failed:', error)
    }
  }, delay)
}

/**
 * Export workspace to JSON (Roadmap §11.2).
 */
export async function exportWorkspace(workspaceId: string): Promise<string> {
  const workspace = await getWorkspace(workspaceId)
  const drawings = await getWorkspaceDrawings(workspaceId)

  const exportData = {
    version: 1,
    workspace,
    drawings: drawings.drawings,
    exported_at: new Date().toISOString(),
  }

  return JSON.stringify(exportData, null, 2)
}

/**
 * Import workspace from JSON (Roadmap §11.2).
 */
export async function importWorkspace(jsonData: string): Promise<Workspace> {
  const data = JSON.parse(jsonData)

  // Create workspace
  const workspace = await createWorkspace({
    name: `${data.workspace.name} (imported)`,
    symbol: data.workspace.symbol,
    timeframe: data.workspace.timeframe,
    layout: data.workspace.layout,
    indicators: data.workspace.indicators,
  })

  // Create drawings
  const drawingIds: string[] = []
  for (const drawing of data.drawings) {
    const created = await createDrawing({
      type: drawing.type,
      symbol: drawing.symbol,
      points: drawing.points,
      style: drawing.style,
    })
    drawingIds.push(created.id)
  }

  // Associate drawings
  await updateWorkspace(workspace.id, { drawing_ids: drawingIds })

  return workspace
}
