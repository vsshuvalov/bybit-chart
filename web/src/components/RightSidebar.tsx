/**
 * RightSidebar Component with Settings Button.
 *
 * Shows list of active modules + button to open SettingsPanel.
 */

import { useState } from 'react'
import SettingsPanel from './SettingsPanel'
import { getModuleSchema } from '../schemas/moduleSchemas'

export default function RightSidebar() {
  const [settingsPanelOpen, setSettingsPanelOpen] = useState(false)
  const [selectedModuleId, setSelectedModuleId] = useState<string | null>(null)

  const handleOpenSettings = (moduleId: string) => {
    setSelectedModuleId(moduleId)
    setSettingsPanelOpen(true)
  }

  const handleSaveSettings = (settings: Record<string, any>) => {
    console.log('[RightSidebar] Save settings:', settings)
    // TODO: Save to workspace via persistence API
    setSettingsPanelOpen(false)
  }

  const selectedSchema = selectedModuleId ? getModuleSchema(selectedModuleId) : null

  return (
    <>
      <div className="right-sidebar">
        <div className="sidebar-header">
          <h3>Active Modules</h3>
        </div>

        <div className="modules-list">
          {/* Example: OrderFlow Imbalance Module */}
          <div className="module-card">
            <div className="module-info">
              <h4>OrderFlow Imbalance</h4>
              <p className="module-status">● Active</p>
            </div>
            <button
              className="settings-btn"
              onClick={() => handleOpenSettings('orderflow_imbalance')}
            >
              ⚙️
            </button>
          </div>

          {/* Example: CVD Module */}
          <div className="module-card">
            <div className="module-info">
              <h4>CVD</h4>
              <p className="module-status">● Active</p>
            </div>
            <button
              className="settings-btn"
              onClick={() => handleOpenSettings('cvd')}
            >
              ⚙️
            </button>
          </div>

          {/* Example: Delta Module */}
          <div className="module-card inactive">
            <div className="module-info">
              <h4>Volume Delta</h4>
              <p className="module-status">○ Inactive</p>
            </div>
            <button className="settings-btn" disabled>
              ⚙️
            </button>
          </div>
        </div>

        <style>{`
          .right-sidebar {
            width: 280px;
            background: var(--bg-secondary);
            border-left: 1px solid var(--border-default);
            display: flex;
            flex-direction: column;
            overflow-y: auto;
          }

          .sidebar-header {
            padding: var(--spacing-md);
            border-bottom: 1px solid var(--border-default);
          }

          .sidebar-header h3 {
            font-size: 14px;
            font-weight: 600;
            margin: 0;
            color: var(--text-primary);
          }

          .modules-list {
            display: flex;
            flex-direction: column;
            gap: var(--spacing-sm);
            padding: var(--spacing-md);
          }

          .module-card {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: var(--spacing-sm);
            background: var(--bg-tertiary);
            border-radius: var(--radius-sm);
            border: 1px solid var(--border-default);
          }

          .module-card.inactive {
            opacity: 0.5;
          }

          .module-info h4 {
            font-size: 13px;
            font-weight: 500;
            margin: 0 0 4px 0;
            color: var(--text-primary);
          }

          .module-status {
            font-size: 11px;
            color: var(--text-secondary);
            margin: 0;
          }

          .module-card:not(.inactive) .module-status {
            color: var(--status-success);
          }

          .settings-btn {
            background: none;
            border: none;
            font-size: 20px;
            cursor: pointer;
            padding: 4px 8px;
            border-radius: var(--radius-sm);
            opacity: 0.6;
          }

          .settings-btn:hover:not(:disabled) {
            background: var(--bg-primary);
            opacity: 1;
          }

          .settings-btn:disabled {
            cursor: not-allowed;
            opacity: 0.3;
          }
        `}</style>
      </div>

      {/* Settings Panel Overlay */}
      {settingsPanelOpen && selectedSchema && (
        <SettingsPanel
          schema={selectedSchema}
          onSave={handleSaveSettings}
          onClose={() => setSettingsPanelOpen(false)}
        />
      )}
    </>
  )
}
