-- Initial schema for Bybit Platform
-- Migration: 001_initial_schema
-- Date: 2026-08-11
-- Author: Platform Team
-- Description: Workspace, audit log, orders metadata tables

-- Workspace metadata
CREATE TABLE IF NOT EXISTS workspace (
    workspace_id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE workspace IS 'User workspace metadata';
COMMENT ON COLUMN workspace.workspace_id IS 'Auto-increment workspace ID';
COMMENT ON COLUMN workspace.name IS 'Unique workspace name';

-- Audit log
CREATE TABLE IF NOT EXISTS audit_log (
    audit_id BIGSERIAL PRIMARY KEY,
    workspace_id INT REFERENCES workspace(workspace_id),
    event_type VARCHAR(50) NOT NULL,
    user_id VARCHAR(100),
    event_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE audit_log IS 'Audit trail for all platform actions';
COMMENT ON COLUMN audit_log.event_type IS 'Action type: LOGIN, TRADE, CONFIG_CHANGE, etc.';
COMMENT ON COLUMN audit_log.event_data IS 'JSON payload with event details';

CREATE INDEX IF NOT EXISTS idx_audit_workspace ON audit_log(workspace_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at DESC);

-- Orders metadata (для будущего execution - Roadmap Этап 9-11)
CREATE TABLE IF NOT EXISTS orders (
    order_id BIGSERIAL PRIMARY KEY,
    workspace_id INT REFERENCES workspace(workspace_id),
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
COMMENT ON COLUMN orders.side IS 'Order side: BUY or SELL';
COMMENT ON COLUMN orders.order_type IS 'Order type: MARKET, LIMIT, STOP, STOP_LIMIT';
COMMENT ON COLUMN orders.status IS 'Order status: PENDING, FILLED, CANCELLED, REJECTED';

CREATE INDEX IF NOT EXISTS idx_orders_workspace ON orders(workspace_id);
CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);

-- Insert default workspace
INSERT INTO workspace (name) VALUES ('default') ON CONFLICT (name) DO NOTHING;

-- Verification queries
DO $$
BEGIN
    RAISE NOTICE 'Migration 001_initial_schema completed successfully';
    RAISE NOTICE 'Tables created: workspace, audit_log, orders';
    RAISE NOTICE 'Indexes created: 9 total';
END $$;
