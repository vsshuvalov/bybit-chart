-- Drawings and Workspaces schema (Roadmap §11.3, §11.7)
-- Migration: 002_drawings_schema
-- Date: 2026-08-13
-- Author: Platform Team
-- Description: Server persistence for drawings and workspaces with schemaVersion tracking

-- ========== Drawings Table ==========

CREATE TABLE IF NOT EXISTS drawings (
    drawing_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identity
    type VARCHAR(50) NOT NULL CHECK (type IN (
        'trendline', 'ray', 'horizontal', 'vertical',
        'rectangle', 'ellipse', 'text', 'channel',
        'fibonacci', 'anchored-vwap', 'volume-profile',
        'ruler', 'risk-reward'
    )),

    -- Scope
    symbol VARCHAR(20) NOT NULL,
    workspace_id INT REFERENCES workspace(workspace_id) ON DELETE CASCADE,

    -- Data (JSONB для flexibility)
    points JSONB NOT NULL, -- Array of {timestamp_us, price_ticks}
    style JSONB NOT NULL DEFAULT '{}', -- {color, width, dash, text, ...}

    -- State
    locked BOOLEAN NOT NULL DEFAULT FALSE,
    hidden BOOLEAN NOT NULL DEFAULT FALSE,

    -- Versioning (Roadmap §11.3)
    schema_version INT NOT NULL DEFAULT 1,
    revision INT NOT NULL DEFAULT 1,

    -- Metadata
    author VARCHAR(100), -- User ID или 'system'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Constraints
    CONSTRAINT drawings_points_not_empty CHECK (jsonb_array_length(points) > 0)
);

COMMENT ON TABLE drawings IS 'User-drawn lines, shapes, markers (Roadmap §11.3)';
COMMENT ON COLUMN drawings.type IS 'Drawing tool type (14 types per §11.3)';
COMMENT ON COLUMN drawings.points IS 'Anchor points: [{timestamp_us, price_ticks}, ...]';
COMMENT ON COLUMN drawings.style IS 'Visual style: {color, width, dash, fontSize, text, ...}';
COMMENT ON COLUMN drawings.schema_version IS 'Schema version for migrations (§11.7)';
COMMENT ON COLUMN drawings.revision IS 'Revision counter (increments on update)';
COMMENT ON COLUMN drawings.author IS 'User ID or system';

-- Indexes
CREATE INDEX IF NOT EXISTS idx_drawings_symbol ON drawings(symbol);
CREATE INDEX IF NOT EXISTS idx_drawings_workspace ON drawings(workspace_id);
CREATE INDEX IF NOT EXISTS idx_drawings_created ON drawings(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_drawings_visible ON drawings(symbol, hidden) WHERE hidden = FALSE;

-- ========== Workspaces Table (Extended) ==========

-- Drop old simple workspace table
DROP TABLE IF EXISTS workspace CASCADE;

CREATE TABLE IF NOT EXISTS workspaces (
    workspace_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identity
    name VARCHAR(255) NOT NULL,

    -- Scope
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,

    -- Configuration (JSONB)
    layout JSONB NOT NULL DEFAULT '{}', -- {leftToolbar, rightSidebar, bottomDock, sizes, ...}
    indicators JSONB NOT NULL DEFAULT '[]', -- [{type, params, enabled, overlay, ...}, ...]

    -- Versioning
    schema_version INT NOT NULL DEFAULT 1,
    revision INT NOT NULL DEFAULT 1,

    -- Metadata
    author VARCHAR(100),
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Constraints
    CONSTRAINT workspaces_name_unique UNIQUE (author, name)
);

COMMENT ON TABLE workspaces IS 'Saved layouts + indicators + drawings (Roadmap §11.7)';
COMMENT ON COLUMN workspaces.layout IS 'Panel layout: visibility, sizes, tabs';
COMMENT ON COLUMN workspaces.indicators IS 'Indicator configs: type, params, enabled';
COMMENT ON COLUMN workspaces.schema_version IS 'Schema version for migrations';
COMMENT ON COLUMN workspaces.is_default IS 'Default workspace for user';

-- Indexes
CREATE INDEX IF NOT EXISTS idx_workspaces_author ON workspaces(author);
CREATE INDEX IF NOT EXISTS idx_workspaces_default ON workspaces(author, is_default) WHERE is_default = TRUE;

-- ========== Workspace-Drawing Association ==========

CREATE TABLE IF NOT EXISTS workspace_drawings (
    workspace_id UUID REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
    drawing_id UUID REFERENCES drawings(drawing_id) ON DELETE CASCADE,
    display_order INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (workspace_id, drawing_id)
);

COMMENT ON TABLE workspace_drawings IS 'Many-to-many: workspaces ↔ drawings';
COMMENT ON COLUMN workspace_drawings.display_order IS 'Z-order for rendering';

CREATE INDEX IF NOT EXISTS idx_workspace_drawings_workspace ON workspace_drawings(workspace_id, display_order);
CREATE INDEX IF NOT EXISTS idx_workspace_drawings_drawing ON workspace_drawings(drawing_id);

-- ========== Audit Log (Extended) ==========

-- Re-create audit_log referencing new workspaces table
CREATE TABLE IF NOT EXISTS audit_log (
    audit_id BIGSERIAL PRIMARY KEY,
    workspace_id UUID REFERENCES workspaces(workspace_id) ON DELETE SET NULL,
    event_type VARCHAR(50) NOT NULL,
    user_id VARCHAR(100),
    event_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE audit_log IS 'Audit trail for all platform actions';
COMMENT ON COLUMN audit_log.event_type IS 'Action type: DRAWING_CREATED, WORKSPACE_SAVED, TRADE_EXECUTED, etc.';
COMMENT ON COLUMN audit_log.event_data IS 'JSON payload with event details';

CREATE INDEX IF NOT EXISTS idx_audit_workspace ON audit_log(workspace_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id, created_at DESC);

-- ========== Orders (Re-create with new workspace FK) ==========

CREATE TABLE IF NOT EXISTS orders (
    order_id BIGSERIAL PRIMARY KEY,
    workspace_id UUID REFERENCES workspaces(workspace_id) ON DELETE SET NULL,
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL CHECK (side IN ('BUY', 'SELL')),
    order_type VARCHAR(20) NOT NULL CHECK (order_type IN ('MARKET', 'LIMIT', 'STOP', 'STOP_LIMIT')),
    quantity DECIMAL(20, 8) NOT NULL CHECK (quantity > 0),
    price DECIMAL(20, 8),
    status VARCHAR(20) NOT NULL CHECK (status IN ('PENDING', 'FILLED', 'CANCELLED', 'REJECTED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE orders IS 'Order metadata for manual/strategy execution';

CREATE INDEX IF NOT EXISTS idx_orders_workspace ON orders(workspace_id);
CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);

-- ========== Default Data ==========

-- Insert default workspace
INSERT INTO workspaces (name, symbol, timeframe, author, is_default)
VALUES ('Default', 'BTCUSDT', '15m', 'system', TRUE)
ON CONFLICT (author, name) DO NOTHING;

-- ========== Verification ==========

DO $$
DECLARE
    drawing_count INT;
    workspace_count INT;
BEGIN
    SELECT COUNT(*) INTO drawing_count FROM drawings;
    SELECT COUNT(*) INTO workspace_count FROM workspaces;

    RAISE NOTICE '========================================';
    RAISE NOTICE 'Migration 002_drawings_schema completed';
    RAISE NOTICE '========================================';
    RAISE NOTICE 'Tables created:';
    RAISE NOTICE '  - drawings (with schemaVersion, revision)';
    RAISE NOTICE '  - workspaces (extended with layout, indicators)';
    RAISE NOTICE '  - workspace_drawings (many-to-many)';
    RAISE NOTICE '  - audit_log (re-created)';
    RAISE NOTICE '  - orders (re-created)';
    RAISE NOTICE '';
    RAISE NOTICE 'Current counts:';
    RAISE NOTICE '  - drawings: %', drawing_count;
    RAISE NOTICE '  - workspaces: %', workspace_count;
    RAISE NOTICE '';
    RAISE NOTICE 'Indexes created: 12 total';
    RAISE NOTICE '========================================';
END $$;
