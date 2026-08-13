/**
 * WorkspaceSelector Component (Roadmap §11.7).
 *
 * Dropdown menu для workspace:
 * - List all workspaces
 * - Current workspace highlighted
 * - Switch workspace → reload drawings/indicators
 * - Create New Workspace button
 *
 * Integration:
 * - useWorkspaces hook (React Query)
 * - Save current workspace to localStorage
 * - Load workspace → apply layout/indicators
 */

import { useState, useRef, useEffect } from 'react'
import { useWorkspaces, useCreateWorkspace } from '../hooks/usePersistence'

interface WorkspaceSelectorProps {
  currentWorkspaceId?: string
  onSelectWorkspace: (workspaceId: string) => void
}

export default function WorkspaceSelector({
  currentWorkspaceId,
  onSelectWorkspace,
}: WorkspaceSelectorProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Fetch workspaces
  const { data: workspacesData, isLoading } = useWorkspaces()
  const createWorkspaceMutation = useCreateWorkspace()

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside)
      return () => document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [isOpen])

  const currentWorkspace = workspacesData?.workspaces.find(
    (w) => w.id === currentWorkspaceId
  )

  const handleCreateWorkspace = async (name: string) => {
    createWorkspaceMutation.mutate(
      {
        name,
        symbol: 'BTCUSDT',
        timeframe: '15m',
        layout: {},
        indicators: [],
      },
      {
        onSuccess: (newWorkspace) => {
          console.log('[WorkspaceSelector] Created:', newWorkspace)
          onSelectWorkspace(newWorkspace.id)
          setShowCreateDialog(false)
        },
      }
    )
  }

  return (
    <div className="workspace-selector" ref={dropdownRef}>
      <button
        className="workspace-btn"
        onClick={() => setIsOpen(!isOpen)}
      >
        {currentWorkspace?.name || 'Select Workspace'} ▾
      </button>

      {isOpen && (
        <div className="workspace-dropdown">
          {isLoading && <div className="dropdown-item loading">Loading...</div>}

          {workspacesData?.workspaces.map((workspace) => (
            <button
              key={workspace.id}
              className={`dropdown-item ${workspace.id === currentWorkspaceId ? 'active' : ''}`}
              onClick={() => {
                onSelectWorkspace(workspace.id)
                setIsOpen(false)
              }}
            >
              <div className="workspace-name">
                <span>{workspace.name}</span>
                {workspace.id === currentWorkspaceId && (
                  <span className="checkmark">✓</span>
                )}
              </div>
              <div className="workspace-meta">
                {workspace.symbol} • {workspace.timeframe}
              </div>
            </button>
          ))}

          <div className="dropdown-divider" />

          <button
            className="dropdown-item create-new"
            onClick={() => {
              setShowCreateDialog(true)
              setIsOpen(false)
            }}
          >
            ➕ Create New Workspace
          </button>
        </div>
      )}

      {/* Create Workspace Dialog */}
      {showCreateDialog && (
        <CreateWorkspaceDialog
          onCreate={handleCreateWorkspace}
          onCancel={() => setShowCreateDialog(false)}
          isCreating={createWorkspaceMutation.isPending}
        />
      )}

      <style>{`
        .workspace-selector {
          position: relative;
        }

        .workspace-btn {
          background: var(--bg-tertiary);
          border: 1px solid var(--border-default);
          color: var(--text-primary);
          padding: 6px 12px;
          border-radius: var(--radius-sm);
          font-size: 14px;
          cursor: pointer;
          display: flex;
          align-items: center;
          gap: 6px;
          transition: all 0.2s;
        }

        .workspace-btn:hover {
          background: var(--bg-primary);
          border-color: var(--border-highlight);
        }

        .workspace-dropdown {
          position: absolute;
          top: calc(100% + 4px);
          left: 0;
          min-width: 280px;
          background: var(--bg-secondary);
          border: 1px solid var(--border-default);
          border-radius: var(--radius-md);
          box-shadow: var(--shadow-lg);
          z-index: 3000;
          max-height: 400px;
          overflow-y: auto;
        }

        .dropdown-item {
          width: 100%;
          background: none;
          border: none;
          color: var(--text-primary);
          padding: 12px 14px;
          text-align: left;
          cursor: pointer;
          display: flex;
          flex-direction: column;
          align-items: flex-start;
          gap: 4px;
          transition: background 0.15s;
          font-size: 14px;
          position: relative;
          min-height: 50px;
        }

        .dropdown-item:hover {
          background: var(--bg-tertiary);
        }

        .dropdown-item.active {
          background: rgba(41, 98, 255, 0.15);
        }

        .dropdown-item.loading {
          color: var(--text-secondary);
          cursor: default;
        }

        .dropdown-item.create-new {
          color: var(--accent-blue);
          font-weight: 500;
        }

        .workspace-name {
          font-weight: 500;
          display: flex;
          align-items: center;
          gap: 8px;
          width: 100%;
          justify-content: space-between;
        }

        .workspace-meta {
          font-size: 11px;
          color: var(--text-secondary);
        }

        .checkmark {
          color: var(--accent-blue);
          font-size: 16px;
        }

        .dropdown-divider {
          height: 1px;
          background: var(--border-default);
          margin: 4px 0;
        }
      `}</style>
    </div>
  )
}

// ========== Create Workspace Dialog ==========

interface CreateWorkspaceDialogProps {
  onCreate: (name: string) => void
  onCancel: () => void
  isCreating: boolean
}

function CreateWorkspaceDialog({
  onCreate,
  onCancel,
  isCreating,
}: CreateWorkspaceDialogProps) {
  const [name, setName] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (name.trim()) {
      onCreate(name.trim())
    }
  }

  return (
    <div className="dialog-overlay" onClick={onCancel}>
      <div className="dialog-box" onClick={(e) => e.stopPropagation()}>
        <h3>Create New Workspace</h3>

        <form onSubmit={handleSubmit}>
          <label>
            Workspace Name
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. BTC Scalping"
              autoFocus
              disabled={isCreating}
            />
          </label>

          <div className="dialog-actions">
            <button
              type="button"
              className="btn-secondary"
              onClick={onCancel}
              disabled={isCreating}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn-primary"
              disabled={!name.trim() || isCreating}
            >
              {isCreating ? 'Creating...' : 'Create'}
            </button>
          </div>
        </form>

        <style>{`
          .dialog-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.7);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 4000;
          }

          .dialog-box {
            background: var(--bg-secondary);
            border: 1px solid var(--border-default);
            border-radius: var(--radius-md);
            padding: var(--spacing-lg);
            width: 400px;
            box-shadow: var(--shadow-lg);
          }

          .dialog-box h3 {
            margin: 0 0 var(--spacing-md) 0;
            font-size: 18px;
            font-weight: 600;
          }

          .dialog-box label {
            display: block;
            font-size: 13px;
            font-weight: 500;
            margin-bottom: var(--spacing-md);
          }

          .dialog-box input {
            width: 100%;
            padding: var(--spacing-sm);
            margin-top: var(--spacing-xs);
            background: var(--bg-primary);
            border: 1px solid var(--border-default);
            border-radius: var(--radius-sm);
            color: var(--text-primary);
            font-size: 14px;
          }

          .dialog-box input:focus {
            outline: 2px solid var(--accent-blue);
            outline-offset: 0;
          }

          .dialog-actions {
            display: flex;
            justify-content: flex-end;
            gap: var(--spacing-sm);
            margin-top: var(--spacing-lg);
          }

          .btn-primary,
          .btn-secondary {
            padding: var(--spacing-sm) var(--spacing-md);
            border-radius: var(--radius-sm);
            font-size: 14px;
            cursor: pointer;
            border: none;
          }

          .btn-primary {
            background: var(--accent-blue);
            color: white;
          }

          .btn-primary:hover:not(:disabled) {
            background: #1e53e5;
          }

          .btn-primary:disabled {
            opacity: 0.5;
            cursor: not-allowed;
          }

          .btn-secondary {
            background: var(--bg-tertiary);
            color: var(--text-primary);
          }

          .btn-secondary:hover:not(:disabled) {
            background: var(--border-highlight);
          }
        `}</style>
      </div>
    </div>
  )
}
