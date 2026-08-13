/**
 * Test component для проверки persistence hooks (Roadmap §11.3, §11.7).
 *
 * Temporary component для тестирования:
 * - useDrawings - list drawings
 * - useCreateDrawing - create drawing
 * - useWorkspaces - list workspaces
 * - useCreateWorkspace - create workspace
 *
 * После тестирования можно удалить или интегрировать в реальные компоненты.
 */

import { useState } from 'react'
import {
  useDrawings,
  useCreateDrawing,
  useWorkspaces,
  useCreateWorkspace,
} from '../hooks/usePersistence'

export default function PersistenceTest() {
  const [symbol] = useState('BTCUSDT')

  // List drawings
  const { data: drawingsData, isLoading: drawingsLoading, error: drawingsError } = useDrawings(symbol)

  // Create drawing mutation
  const createDrawingMutation = useCreateDrawing()

  // List workspaces
  const { data: workspacesData, isLoading: workspacesLoading } = useWorkspaces()

  // Create workspace mutation
  const createWorkspaceMutation = useCreateWorkspace()

  const handleCreateTestDrawing = () => {
    createDrawingMutation.mutate({
      type: 'horizontal',
      symbol,
      points: [
        {
          timestamp_us: Date.now() * 1000,
          price_ticks: 50000 + Math.floor(Math.random() * 5000),
        },
      ],
      style: {
        color: '#' + Math.floor(Math.random() * 16777215).toString(16),
        width: 2,
      },
    })
  }

  const handleCreateTestWorkspace = () => {
    createWorkspaceMutation.mutate({
      name: `Test Workspace ${Date.now()}`,
      symbol: 'BTCUSDT',
      timeframe: '15m',
      layout: {
        leftToolbar: true,
        rightSidebar: false,
      },
      indicators: [
        {
          type: 'ema',
          period: 20,
        },
      ],
    })
  }

  return (
    <div style={{
      padding: '20px',
      backgroundColor: '#1a1a1a',
      color: '#fff',
      maxWidth: '800px',
      margin: '20px auto',
      borderRadius: '8px',
      border: '2px solid #333',
      maxHeight: '400px',
      overflowY: 'auto'
    }}>
      <h2 style={{ margin: '0 0 15px 0', fontSize: '18px' }}>🧪 Persistence API Test</h2>

      {/* Drawings Section */}
      <div style={{ marginBottom: '30px' }}>
        <h3>📊 Drawings ({symbol})</h3>

        {drawingsLoading && <p>Loading drawings...</p>}
        {drawingsError && <p style={{ color: '#ff5555' }}>Error: {String(drawingsError)}</p>}

        {drawingsData && (
          <div>
            <p>
              ✅ Loaded {drawingsData.count} drawing(s)
            </p>
            <pre style={{ background: '#2a2a2a', padding: '10px', overflow: 'auto', maxHeight: '200px' }}>
              {JSON.stringify(drawingsData.drawings, null, 2)}
            </pre>
          </div>
        )}

        <button
          onClick={handleCreateTestDrawing}
          disabled={createDrawingMutation.isPending}
          style={{
            padding: '10px 20px',
            backgroundColor: '#4caf50',
            color: '#fff',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer',
            marginTop: '10px',
          }}
        >
          {createDrawingMutation.isPending ? 'Creating...' : '➕ Create Test Drawing'}
        </button>

        {createDrawingMutation.isSuccess && (
          <p style={{ color: '#4caf50' }}>✅ Drawing created successfully!</p>
        )}
        {createDrawingMutation.isError && (
          <p style={{ color: '#ff5555' }}>❌ Error: {String(createDrawingMutation.error)}</p>
        )}
      </div>

      {/* Workspaces Section */}
      <div>
        <h3>🗂️ Workspaces</h3>

        {workspacesLoading && <p>Loading workspaces...</p>}

        {workspacesData && (
          <div>
            <p>
              ✅ Loaded {workspacesData.count} workspace(s)
            </p>
            <pre style={{ background: '#2a2a2a', padding: '10px', overflow: 'auto', maxHeight: '200px' }}>
              {JSON.stringify(workspacesData.workspaces, null, 2)}
            </pre>
          </div>
        )}

        <button
          onClick={handleCreateTestWorkspace}
          disabled={createWorkspaceMutation.isPending}
          style={{
            padding: '10px 20px',
            backgroundColor: '#2196f3',
            color: '#fff',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer',
            marginTop: '10px',
          }}
        >
          {createWorkspaceMutation.isPending ? 'Creating...' : '➕ Create Test Workspace'}
        </button>

        {createWorkspaceMutation.isSuccess && (
          <p style={{ color: '#4caf50' }}>✅ Workspace created successfully!</p>
        )}
        {createWorkspaceMutation.isError && (
          <p style={{ color: '#ff5555' }}>❌ Error: {String(createWorkspaceMutation.error)}</p>
        )}
      </div>

      {/* Instructions */}
      <div style={{ marginTop: '30px', padding: '15px', background: '#2a2a2a', borderRadius: '4px' }}>
        <h4>📋 How to Use</h4>
        <ol>
          <li>Click "Create Test Drawing" — should create a horizontal line</li>
          <li>Check drawings list updates automatically (React Query cache)</li>
          <li>Click "Create Test Workspace" — should create new workspace</li>
          <li>Open browser DevTools Console to see persistence logs</li>
          <li>Check Network tab to see API calls</li>
        </ol>
        <p>
          <strong>Expected:</strong> Green success messages, data updates, no errors
        </p>
      </div>
    </div>
  )
}
