/**
 * SettingsPanel Component (Roadmap §11.1).
 *
 * Schema-driven settings UI для модулей (OrderFlow, CVD, Delta, etc.).
 * Tabs: General, Calculation, Filters, Style, Data Quality, Version/Diagnostics.
 *
 * Features:
 * - Auto-generated form from schema
 * - Real-time validation
 * - Save to workspace (PostgreSQL persistence)
 * - Apply changes to running modules
 */

import { useState } from 'react'
import { ModuleSchema, FieldSchema } from '../schemas/moduleSchemas'

interface SettingsPanelProps {
  schema: ModuleSchema
  onSave: (settings: Record<string, any>) => void
  onClose: () => void
  initialValues?: Record<string, any>
}

export default function SettingsPanel({
  schema,
  onSave,
  onClose,
  initialValues = {},
}: SettingsPanelProps) {
  const [activeTab, setActiveTab] = useState(schema.tabs[0]?.id || '')
  const [values, setValues] = useState<Record<string, any>>(() => {
    // Initialize with defaultValues from schema
    const defaults: Record<string, any> = {}
    schema.tabs.forEach((tab) => {
      tab.fields.forEach((field) => {
        defaults[field.key] = initialValues[field.key] ?? field.defaultValue
      })
    })
    return defaults
  })

  const [errors, setErrors] = useState<Record<string, string>>({})

  const handleChange = (key: string, value: any, field: FieldSchema) => {
    setValues((prev) => ({ ...prev, [key]: value }))

    // Validate
    if (field.validator) {
      const error = field.validator(value)
      setErrors((prev) => ({
        ...prev,
        [key]: error || '',
      }))
    }
  }

  const handleSave = () => {
    // Check for errors
    const hasErrors = Object.values(errors).some((err) => err)
    if (hasErrors) {
      alert('Please fix validation errors before saving')
      return
    }

    onSave(values)
  }

  const activeTabSchema = schema.tabs.find((t) => t.id === activeTab)

  return (
    <div className="settings-panel">
      {/* Header */}
      <div className="settings-header">
        <h2>{schema.moduleName} Settings</h2>
        <button className="close-btn" onClick={onClose}>
          ✕
        </button>
      </div>

      {/* Tabs */}
      <div className="settings-tabs">
        {schema.tabs.map((tab) => (
          <button
            key={tab.id}
            className={`tab-btn ${activeTab === tab.id ? 'active' : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="settings-content">
        {activeTabSchema && (
          <div className="fields-container">
            {activeTabSchema.fields.map((field) => (
              <FieldRenderer
                key={field.key}
                field={field}
                value={values[field.key]}
                error={errors[field.key]}
                onChange={(value) => handleChange(field.key, value, field)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="settings-footer">
        <button className="btn-secondary" onClick={onClose}>
          Cancel
        </button>
        <button className="btn-primary" onClick={handleSave}>
          Save Settings
        </button>
      </div>

      <style>{`
        .settings-panel {
          position: fixed;
          top: 0;
          right: 0;
          width: 450px;
          height: 100vh;
          background: var(--bg-secondary);
          border-left: 1px solid var(--border-default);
          display: flex;
          flex-direction: column;
          z-index: 2000;
          box-shadow: var(--shadow-lg);
        }

        .settings-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: var(--spacing-md);
          border-bottom: 1px solid var(--border-default);
        }

        .settings-header h2 {
          font-size: 18px;
          font-weight: 600;
          margin: 0;
        }

        .close-btn {
          background: none;
          border: none;
          color: var(--text-secondary);
          font-size: 24px;
          cursor: pointer;
          padding: 0;
          width: 32px;
          height: 32px;
          display: flex;
          align-items: center;
          justify-content: center;
          border-radius: var(--radius-sm);
        }

        .close-btn:hover {
          background: var(--bg-tertiary);
          color: var(--text-primary);
        }

        .settings-tabs {
          display: flex;
          gap: 2px;
          padding: var(--spacing-sm) var(--spacing-md) 0;
          border-bottom: 1px solid var(--border-default);
          overflow-x: auto;
        }

        .tab-btn {
          background: none;
          border: none;
          color: var(--text-secondary);
          padding: var(--spacing-sm) var(--spacing-md);
          cursor: pointer;
          font-size: 13px;
          border-bottom: 2px solid transparent;
          white-space: nowrap;
        }

        .tab-btn:hover {
          color: var(--text-primary);
        }

        .tab-btn.active {
          color: var(--accent-blue);
          border-bottom-color: var(--accent-blue);
        }

        .settings-content {
          flex: 1;
          overflow-y: auto;
          padding: var(--spacing-md);
        }

        .fields-container {
          display: flex;
          flex-direction: column;
          gap: var(--spacing-md);
        }

        .settings-footer {
          display: flex;
          justify-content: flex-end;
          gap: var(--spacing-sm);
          padding: var(--spacing-md);
          border-top: 1px solid var(--border-default);
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

        .btn-primary:hover {
          background: #1e53e5;
        }

        .btn-secondary {
          background: var(--bg-tertiary);
          color: var(--text-primary);
        }

        .btn-secondary:hover {
          background: var(--border-highlight);
        }
      `}</style>
    </div>
  )
}

// ========== Field Renderer ==========

interface FieldRendererProps {
  field: FieldSchema
  value: any
  error?: string
  onChange: (value: any) => void
}

function FieldRenderer({ field, value, error, onChange }: FieldRendererProps) {
  return (
    <div className="field-group">
      <label className="field-label">
        {field.label}
        {field.required && <span className="required">*</span>}
      </label>

      {field.description && <p className="field-description">{field.description}</p>}

      <div className="field-input">
        {field.type === 'boolean' && (
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={value}
              onChange={(e) => onChange(e.target.checked)}
            />
            <span>{field.label}</span>
          </label>
        )}

        {field.type === 'number' && (
          <input
            type="number"
            value={value}
            min={field.min}
            max={field.max}
            step={field.step}
            onChange={(e) => onChange(parseFloat(e.target.value))}
          />
        )}

        {field.type === 'range' && (
          <div className="range-input">
            <input
              type="range"
              value={value}
              min={field.min}
              max={field.max}
              step={field.step}
              onChange={(e) => onChange(parseFloat(e.target.value))}
            />
            <span className="range-value">{value}</span>
          </div>
        )}

        {field.type === 'text' && (
          <input
            type="text"
            value={value}
            onChange={(e) => onChange(e.target.value)}
          />
        )}

        {field.type === 'select' && (
          <select value={value} onChange={(e) => onChange(e.target.value)}>
            {field.options?.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        )}

        {field.type === 'color' && (
          <div className="color-input">
            <input
              type="color"
              value={value}
              onChange={(e) => onChange(e.target.value)}
            />
            <span className="color-value">{value}</span>
          </div>
        )}

        {field.type === 'readonly' && (
          <input type="text" value={value} readOnly disabled />
        )}
      </div>

      {error && <p className="field-error">{error}</p>}

      <style>{`
        .field-group {
          display: flex;
          flex-direction: column;
          gap: var(--spacing-xs);
        }

        .field-label {
          font-size: 13px;
          font-weight: 500;
          color: var(--text-primary);
        }

        .field-label .required {
          color: var(--status-error);
          margin-left: 2px;
        }

        .field-description {
          font-size: 12px;
          color: var(--text-secondary);
          margin: 0;
        }

        .field-input input[type="text"],
        .field-input input[type="number"],
        .field-input select {
          width: 100%;
          padding: var(--spacing-sm);
          background: var(--bg-primary);
          border: 1px solid var(--border-default);
          border-radius: var(--radius-sm);
          color: var(--text-primary);
          font-size: 14px;
        }

        .field-input input:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .checkbox-label {
          display: flex;
          align-items: center;
          gap: var(--spacing-sm);
          cursor: pointer;
        }

        .range-input {
          display: flex;
          align-items: center;
          gap: var(--spacing-sm);
        }

        .range-input input[type="range"] {
          flex: 1;
        }

        .range-value {
          font-size: 13px;
          color: var(--text-secondary);
          min-width: 50px;
          text-align: right;
        }

        .color-input {
          display: flex;
          align-items: center;
          gap: var(--spacing-sm);
        }

        .color-input input[type="color"] {
          width: 50px;
          height: 36px;
          border: 1px solid var(--border-default);
          border-radius: var(--radius-sm);
          cursor: pointer;
        }

        .color-value {
          font-size: 13px;
          color: var(--text-secondary);
          font-family: var(--font-mono);
        }

        .field-error {
          font-size: 12px;
          color: var(--status-error);
          margin: 0;
        }
      `}</style>
    </div>
  )
}
