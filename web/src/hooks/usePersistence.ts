/**
 * React hooks для server persistence (Roadmap §11.3, §11.7).
 *
 * Features:
 * - Auto-save на сервер (debounced)
 * - Optimistic updates для UI responsiveness
 * - Error handling и retry logic
 */

import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Drawing,
  DrawingListResponse,
  CreateDrawingRequest,
  UpdateDrawingRequest,
  Workspace,
  WorkspaceListResponse,
  CreateWorkspaceRequest,
  UpdateWorkspaceRequest,
  listDrawings,
  createDrawing,
  getDrawing,
  updateDrawing,
  deleteDrawing,
  listWorkspaces,
  createWorkspace,
  getWorkspace,
  updateWorkspace,
  deleteWorkspace,
  getWorkspaceDrawings,
} from '../api/persistence'

// ========== Drawings Hooks ==========

/**
 * Hook: List drawings for symbol.
 *
 * Usage:
 *   const { data, isLoading, error } = useDrawings('BTCUSDT')
 */
export function useDrawings(
  symbol: string,
  includeHidden = false,
  workspaceId?: string
) {
  return useQuery<DrawingListResponse>({
    queryKey: ['drawings', symbol, includeHidden, workspaceId],
    queryFn: () => listDrawings(symbol, includeHidden, workspaceId),
    staleTime: 30_000, // 30s cache
  })
}

/**
 * Hook: Get single drawing by ID.
 */
export function useDrawing(drawingId: string | null) {
  return useQuery<Drawing>({
    queryKey: ['drawing', drawingId],
    queryFn: () => getDrawing(drawingId!),
    enabled: !!drawingId,
    staleTime: 60_000,
  })
}

/**
 * Hook: Create drawing mutation.
 *
 * Usage:
 *   const createMutation = useCreateDrawing()
 *   createMutation.mutate({ type: 'trendline', symbol: 'BTCUSDT', points: [...], style: {...} })
 */
export function useCreateDrawing() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (request: CreateDrawingRequest) => createDrawing(request),
    onSuccess: (newDrawing) => {
      // Invalidate drawings list
      queryClient.invalidateQueries({ queryKey: ['drawings', newDrawing.symbol] })
      console.log('[Persistence] Drawing created:', newDrawing.id)
    },
    onError: (error) => {
      console.error('[Persistence] Drawing creation failed:', error)
    },
  })
}

/**
 * Hook: Update drawing mutation.
 *
 * Usage:
 *   const updateMutation = useUpdateDrawing()
 *   updateMutation.mutate({ drawingId: 'uuid', updates: { locked: true } })
 */
export function useUpdateDrawing() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ drawingId, updates }: { drawingId: string; updates: UpdateDrawingRequest }) =>
      updateDrawing(drawingId, updates),
    onMutate: async ({ drawingId, updates }) => {
      // Optimistic update
      await queryClient.cancelQueries({ queryKey: ['drawing', drawingId] })

      const previousDrawing = queryClient.getQueryData<Drawing>(['drawing', drawingId])

      if (previousDrawing) {
        queryClient.setQueryData<Drawing>(['drawing', drawingId], {
          ...previousDrawing,
          ...updates,
        })
      }

      return { previousDrawing }
    },
    onError: (error, { drawingId }, context) => {
      // Rollback on error
      if (context?.previousDrawing) {
        queryClient.setQueryData(['drawing', drawingId], context.previousDrawing)
      }
      console.error('[Persistence] Drawing update failed:', error)
    },
    onSuccess: (updatedDrawing) => {
      queryClient.setQueryData(['drawing', updatedDrawing.id], updatedDrawing)
      queryClient.invalidateQueries({ queryKey: ['drawings', updatedDrawing.symbol] })
      console.log('[Persistence] Drawing updated:', updatedDrawing.id)
    },
  })
}

/**
 * Hook: Delete drawing mutation.
 */
export function useDeleteDrawing() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (drawingId: string) => deleteDrawing(drawingId),
    onSuccess: (_, drawingId) => {
      queryClient.invalidateQueries({ queryKey: ['drawings'] })
      queryClient.removeQueries({ queryKey: ['drawing', drawingId] })
      console.log('[Persistence] Drawing deleted:', drawingId)
    },
    onError: (error) => {
      console.error('[Persistence] Drawing deletion failed:', error)
    },
  })
}

// ========== Workspaces Hooks ==========

/**
 * Hook: List workspaces.
 */
export function useWorkspaces(author?: string) {
  return useQuery<WorkspaceListResponse>({
    queryKey: ['workspaces', author],
    queryFn: () => listWorkspaces(author),
    staleTime: 60_000, // 1min cache
  })
}

/**
 * Hook: Get single workspace by ID.
 */
export function useWorkspace(workspaceId: string | null) {
  return useQuery<Workspace>({
    queryKey: ['workspace', workspaceId],
    queryFn: () => getWorkspace(workspaceId!),
    enabled: !!workspaceId,
    staleTime: 60_000,
  })
}

/**
 * Hook: Create workspace mutation.
 */
export function useCreateWorkspace() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (request: CreateWorkspaceRequest) => createWorkspace(request),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      console.log('[Persistence] Workspace created')
    },
    onError: (error) => {
      console.error('[Persistence] Workspace creation failed:', error)
    },
  })
}

/**
 * Hook: Update workspace mutation (with auto-save debounce).
 */
export function useUpdateWorkspace() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ workspaceId, updates }: { workspaceId: string; updates: UpdateWorkspaceRequest }) =>
      updateWorkspace(workspaceId, updates),
    onMutate: async ({ workspaceId, updates }) => {
      // Optimistic update
      await queryClient.cancelQueries({ queryKey: ['workspace', workspaceId] })

      const previousWorkspace = queryClient.getQueryData<Workspace>(['workspace', workspaceId])

      if (previousWorkspace) {
        queryClient.setQueryData<Workspace>(['workspace', workspaceId], {
          ...previousWorkspace,
          ...updates,
        })
      }

      return { previousWorkspace }
    },
    onError: (error, { workspaceId }, context) => {
      if (context?.previousWorkspace) {
        queryClient.setQueryData(['workspace', workspaceId], context.previousWorkspace)
      }
      console.error('[Persistence] Workspace update failed:', error)
    },
    onSuccess: (updatedWorkspace) => {
      queryClient.setQueryData(['workspace', updatedWorkspace.id], updatedWorkspace)
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      console.log('[Persistence] Workspace updated:', updatedWorkspace.id)
    },
  })
}

/**
 * Hook: Delete workspace mutation.
 */
export function useDeleteWorkspace() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (workspaceId: string) => deleteWorkspace(workspaceId),
    onSuccess: (_, workspaceId) => {
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      queryClient.removeQueries({ queryKey: ['workspace', workspaceId] })
      console.log('[Persistence] Workspace deleted:', workspaceId)
    },
    onError: (error) => {
      console.error('[Persistence] Workspace deletion failed:', error)
    },
  })
}

/**
 * Hook: Get workspace drawings.
 */
export function useWorkspaceDrawings(workspaceId: string | null) {
  return useQuery<DrawingListResponse>({
    queryKey: ['workspace-drawings', workspaceId],
    queryFn: () => getWorkspaceDrawings(workspaceId!),
    enabled: !!workspaceId,
    staleTime: 30_000,
  })
}

// ========== Auto-Save Hook ==========

/**
 * Hook: Auto-save workspace on layout/indicator changes.
 *
 * Usage:
 *   useAutoSaveWorkspace(workspaceId, { layout, indicators }, 1000)
 */
export function useAutoSaveWorkspace(
  workspaceId: string | null,
  updates: UpdateWorkspaceRequest,
  delay = 1000
) {
  const updateMutation = useUpdateWorkspace()

  useEffect(() => {
    if (!workspaceId) return

    const timer = setTimeout(() => {
      updateMutation.mutate({ workspaceId, updates })
    }, delay)

    return () => clearTimeout(timer)
  }, [workspaceId, JSON.stringify(updates), delay])
}

/**
 * Hook: Auto-save drawing on style/position changes.
 */
export function useAutoSaveDrawing(
  drawingId: string | null,
  updates: UpdateDrawingRequest,
  delay = 500
) {
  const updateMutation = useUpdateDrawing()

  useEffect(() => {
    if (!drawingId) return

    const timer = setTimeout(() => {
      updateMutation.mutate({ drawingId, updates })
    }, delay)

    return () => clearTimeout(timer)
  }, [drawingId, JSON.stringify(updates), delay])
}

// ========== Active Workspace Hook ==========

/**
 * Hook: Manage active workspace (load on mount, auto-save on changes).
 *
 * Usage:
 *   const { workspace, updateLayout, updateIndicators } = useActiveWorkspace('workspace-uuid')
 */
export function useActiveWorkspace(workspaceId: string | null) {
  const { data: workspace, isLoading, error } = useWorkspace(workspaceId)
  const updateMutation = useUpdateWorkspace()

  const [pendingUpdates, setPendingUpdates] = useState<UpdateWorkspaceRequest>({})

  // Auto-save pending updates (debounced)
  useAutoSaveWorkspace(workspaceId, pendingUpdates, 1000)

  const updateLayout = (layout: Record<string, any>) => {
    setPendingUpdates((prev) => ({ ...prev, layout }))
  }

  const updateIndicators = (indicators: Array<Record<string, any>>) => {
    setPendingUpdates((prev) => ({ ...prev, indicators }))
  }

  return {
    workspace,
    isLoading,
    error,
    updateLayout,
    updateIndicators,
    isSaving: updateMutation.isPending,
  }
}
