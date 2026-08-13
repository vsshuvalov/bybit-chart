/**
 * Schema definitions для settings panels (Roadmap §11.1).
 *
 * Each module (OrderFlow Imbalance, CVD, Delta, Drawings) имеет schema
 * для auto-generation settings UI с табами:
 * - General: основные параметры
 * - Calculation: формулы, алгоритмы
 * - Filters: фильтры данных
 * - Style: визуальные настройки
 * - Data Quality: проверки данных
 * - Version/Diagnostics: debug info
 */

export type FieldType =
  | 'number'
  | 'boolean'
  | 'select'
  | 'color'
  | 'range'
  | 'text'
  | 'readonly'

export interface FieldSchema {
  key: string
  label: string
  type: FieldType
  defaultValue: any
  description?: string

  // For 'number' and 'range'
  min?: number
  max?: number
  step?: number

  // For 'select'
  options?: Array<{ value: any; label: string }>

  // Validation
  required?: boolean
  validator?: (value: any) => string | null // returns error message or null
}

export interface TabSchema {
  id: string
  label: string
  fields: FieldSchema[]
}

export interface ModuleSchema {
  moduleId: string
  moduleName: string
  version: string
  tabs: TabSchema[]
}

// ========== Example: OrderFlow Imbalance Module ==========

export const orderFlowImbalanceSchema: ModuleSchema = {
  moduleId: 'orderflow_imbalance',
  moduleName: 'OrderFlow Imbalance',
  version: '1.0.0',
  tabs: [
    {
      id: 'general',
      label: 'General',
      fields: [
        {
          key: 'enabled',
          label: 'Enabled',
          type: 'boolean',
          defaultValue: true,
          description: 'Enable/disable this module',
        },
        {
          key: 'symbol',
          label: 'Symbol',
          type: 'text',
          defaultValue: 'BTCUSDT',
          description: 'Trading pair symbol',
        },
        {
          key: 'timeframe',
          label: 'Timeframe',
          type: 'select',
          defaultValue: '15m',
          options: [
            { value: '1m', label: '1 minute' },
            { value: '5m', label: '5 minutes' },
            { value: '15m', label: '15 minutes' },
            { value: '1h', label: '1 hour' },
          ],
        },
      ],
    },
    {
      id: 'calculation',
      label: 'Calculation',
      fields: [
        {
          key: 'imbalanceThreshold',
          label: 'Imbalance Threshold',
          type: 'range',
          defaultValue: 2.0,
          min: 1.0,
          max: 10.0,
          step: 0.1,
          description: 'Bid/Ask imbalance ratio threshold',
        },
        {
          key: 'volumeMinimum',
          label: 'Minimum Volume',
          type: 'number',
          defaultValue: 10000,
          min: 0,
          description: 'Minimum volume to consider (USD)',
        },
        {
          key: 'algorithm',
          label: 'Algorithm',
          type: 'select',
          defaultValue: 'ratio',
          options: [
            { value: 'ratio', label: 'Bid/Ask Ratio' },
            { value: 'delta', label: 'Volume Delta' },
            { value: 'weighted', label: 'Weighted Average' },
          ],
        },
      ],
    },
    {
      id: 'filters',
      label: 'Filters',
      fields: [
        {
          key: 'filterSmallTrades',
          label: 'Filter Small Trades',
          type: 'boolean',
          defaultValue: true,
          description: 'Ignore trades below minimum volume',
        },
        {
          key: 'minTradeSize',
          label: 'Min Trade Size (USD)',
          type: 'number',
          defaultValue: 1000,
          min: 0,
        },
        {
          key: 'excludeInternalTransfers',
          label: 'Exclude Internal Transfers',
          type: 'boolean',
          defaultValue: true,
        },
      ],
    },
    {
      id: 'style',
      label: 'Style',
      fields: [
        {
          key: 'buyColor',
          label: 'Buy Color',
          type: 'color',
          defaultValue: '#26a69a',
        },
        {
          key: 'sellColor',
          label: 'Sell Color',
          type: 'color',
          defaultValue: '#ef5350',
        },
        {
          key: 'lineWidth',
          label: 'Line Width',
          type: 'range',
          defaultValue: 2,
          min: 1,
          max: 5,
          step: 1,
        },
        {
          key: 'showLabels',
          label: 'Show Labels',
          type: 'boolean',
          defaultValue: true,
        },
      ],
    },
    {
      id: 'data_quality',
      label: 'Data Quality',
      fields: [
        {
          key: 'validateChecksum',
          label: 'Validate Checksums',
          type: 'boolean',
          defaultValue: true,
          description: 'Verify data integrity',
        },
        {
          key: 'detectGaps',
          label: 'Detect Gaps',
          type: 'boolean',
          defaultValue: true,
          description: 'Alert on missing data',
        },
        {
          key: 'maxGapDuration',
          label: 'Max Gap Duration (seconds)',
          type: 'number',
          defaultValue: 300,
          min: 0,
        },
      ],
    },
    {
      id: 'diagnostics',
      label: 'Version/Diagnostics',
      fields: [
        {
          key: 'version',
          label: 'Module Version',
          type: 'readonly',
          defaultValue: '1.0.0',
        },
        {
          key: 'schemaVersion',
          label: 'Schema Version',
          type: 'readonly',
          defaultValue: 1,
        },
        {
          key: 'lastUpdated',
          label: 'Last Updated',
          type: 'readonly',
          defaultValue: new Date().toISOString(),
        },
        {
          key: 'debug',
          label: 'Debug Mode',
          type: 'boolean',
          defaultValue: false,
          description: 'Enable verbose console logging',
        },
      ],
    },
  ],
}

// ========== Example: CVD Module ==========

export const cvdSchema: ModuleSchema = {
  moduleId: 'cvd',
  moduleName: 'Cumulative Volume Delta',
  version: '1.0.0',
  tabs: [
    {
      id: 'general',
      label: 'General',
      fields: [
        {
          key: 'enabled',
          label: 'Enabled',
          type: 'boolean',
          defaultValue: true,
        },
        {
          key: 'symbol',
          label: 'Symbol',
          type: 'text',
          defaultValue: 'BTCUSDT',
        },
      ],
    },
    {
      id: 'calculation',
      label: 'Calculation',
      fields: [
        {
          key: 'resetInterval',
          label: 'Reset Interval',
          type: 'select',
          defaultValue: 'daily',
          options: [
            { value: 'never', label: 'Never' },
            { value: 'daily', label: 'Daily' },
            { value: 'session', label: 'Per Session' },
          ],
          description: 'When to reset CVD counter',
        },
        {
          key: 'smoothing',
          label: 'Smoothing Period',
          type: 'number',
          defaultValue: 14,
          min: 1,
          max: 100,
          description: 'EMA period for smoothing',
        },
      ],
    },
    {
      id: 'style',
      label: 'Style',
      fields: [
        {
          key: 'positiveColor',
          label: 'Positive Color',
          type: 'color',
          defaultValue: '#26a69a',
        },
        {
          key: 'negativeColor',
          label: 'Negative Color',
          type: 'color',
          defaultValue: '#ef5350',
        },
      ],
    },
    {
      id: 'diagnostics',
      label: 'Version/Diagnostics',
      fields: [
        {
          key: 'version',
          label: 'Module Version',
          type: 'readonly',
          defaultValue: '1.0.0',
        },
      ],
    },
  ],
}

// ========== Registry ==========

export const moduleSchemas: Record<string, ModuleSchema> = {
  orderflow_imbalance: orderFlowImbalanceSchema,
  cvd: cvdSchema,
  // Добавлять новые модули здесь
}

export function getModuleSchema(moduleId: string): ModuleSchema | null {
  return moduleSchemas[moduleId] || null
}
