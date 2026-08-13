"""
PostgreSQL persistence для Drawings и Workspaces (Roadmap §11.3, §11.7).

Замена in-memory storage на production PostgreSQL.

Features:
- schemaVersion tracking для migrations
- revision counter (increments on update)
- author tracking
- JSONB для flexible schema
- Transaction support
"""

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

import asyncpg
from asyncpg import Connection, Pool

from packages.api.persistence_models import (
    Drawing,
    DrawingPoint,
    Workspace,
)

logger = logging.getLogger(__name__)


class PostgreSQLPersistence:
    """PostgreSQL persistence layer для drawings и workspaces."""

    def __init__(self, pool: Pool):
        """
        Args:
            pool: asyncpg connection pool
        """
        self.pool = pool

    @classmethod
    async def create(
        cls,
        host: str = "localhost",
        port: int = 5432,
        database: str = "bybit_platform",
        user: str = "bybit_user",
        password: str | None = None,
        min_size: int = 5,
        max_size: int = 20,
    ) -> "PostgreSQLPersistence":
        """Create persistence with connection pool.

        Args:
            host: PostgreSQL host
            port: PostgreSQL port
            database: Database name
            user: Username
            password: Password (optional, can use .pgpass)
            min_size: Min pool size
            max_size: Max pool size

        Returns:
            PostgreSQLPersistence instance
        """
        pool = await asyncpg.create_pool(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            min_size=min_size,
            max_size=max_size,
        )
        logger.info(
            f"PostgreSQL pool created: {database}@{host}:{port} "
            f"(pool: {min_size}-{max_size})"
        )
        return cls(pool)

    async def close(self):
        """Close connection pool."""
        await self.pool.close()
        logger.info("PostgreSQL pool closed")

    # ========== Drawings CRUD ==========

    async def create_drawing(
        self,
        type: str,
        symbol: str,
        points: list[DrawingPoint],
        style: dict,
        workspace_id: Optional[UUID] = None,
        author: Optional[str] = None,
        schema_version: int = 1,
    ) -> Drawing:
        """Create new drawing.

        Args:
            type: Drawing tool type (trendline, horizontal, etc.)
            symbol: Symbol (BTCUSDT)
            points: Anchor points [{timestamp_us, price_ticks}, ...]
            style: Visual style {color, width, dash, ...}
            workspace_id: Optional workspace UUID
            author: Optional author ID
            schema_version: Schema version (default: 1)

        Returns:
            Created Drawing
        """
        drawing_id = uuid4()
        points_json = [p.model_dump() for p in points]

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO drawings (
                    drawing_id, type, symbol, workspace_id,
                    points, style, schema_version, author,
                    created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), NOW())
                RETURNING
                    drawing_id, type, symbol, workspace_id,
                    points, style, locked, hidden,
                    schema_version, revision, author,
                    created_at, updated_at
                """,
                drawing_id,
                type,
                symbol,
                workspace_id,
                points_json,
                style,
                schema_version,
                author,
            )

        return self._row_to_drawing(row)

    async def get_drawing(self, drawing_id: UUID) -> Optional[Drawing]:
        """Get drawing by ID.

        Args:
            drawing_id: Drawing UUID

        Returns:
            Drawing or None
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    drawing_id, type, symbol, workspace_id,
                    points, style, locked, hidden,
                    schema_version, revision, author,
                    created_at, updated_at
                FROM drawings
                WHERE drawing_id = $1
                """,
                drawing_id,
            )

        return self._row_to_drawing(row) if row else None

    async def list_drawings(
        self,
        symbol: str,
        include_hidden: bool = False,
        workspace_id: Optional[UUID] = None,
    ) -> list[Drawing]:
        """List all drawings for symbol.

        Args:
            symbol: Symbol (BTCUSDT)
            include_hidden: Include hidden drawings (default: False)
            workspace_id: Optional filter by workspace

        Returns:
            List of Drawings
        """
        query = """
            SELECT
                drawing_id, type, symbol, workspace_id,
                points, style, locked, hidden,
                schema_version, revision, author,
                created_at, updated_at
            FROM drawings
            WHERE symbol = $1
        """
        params = [symbol]

        if not include_hidden:
            query += " AND hidden = FALSE"

        if workspace_id:
            query += f" AND workspace_id = ${len(params) + 1}"
            params.append(workspace_id)

        query += " ORDER BY created_at DESC"

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [self._row_to_drawing(row) for row in rows]

    async def update_drawing(
        self,
        drawing_id: UUID,
        points: Optional[list[DrawingPoint]] = None,
        style: Optional[dict] = None,
        locked: Optional[bool] = None,
        hidden: Optional[bool] = None,
    ) -> Optional[Drawing]:
        """Update drawing.

        Args:
            drawing_id: Drawing UUID
            points: Optional new points
            style: Optional new style
            locked: Optional locked state
            hidden: Optional hidden state

        Returns:
            Updated Drawing or None
        """
        updates = []
        params = []
        param_idx = 1

        if points is not None:
            updates.append(f"points = ${param_idx}")
            params.append([p.model_dump() for p in points])
            param_idx += 1

        if style is not None:
            updates.append(f"style = ${param_idx}")
            params.append(style)
            param_idx += 1

        if locked is not None:
            updates.append(f"locked = ${param_idx}")
            params.append(locked)
            param_idx += 1

        if hidden is not None:
            updates.append(f"hidden = ${param_idx}")
            params.append(hidden)
            param_idx += 1

        if not updates:
            # No updates, just return existing
            return await self.get_drawing(drawing_id)

        # Increment revision, update timestamp
        updates.append("revision = revision + 1")
        updates.append("updated_at = NOW()")

        params.append(drawing_id)
        query = f"""
            UPDATE drawings
            SET {', '.join(updates)}
            WHERE drawing_id = ${param_idx}
            RETURNING
                drawing_id, type, symbol, workspace_id,
                points, style, locked, hidden,
                schema_version, revision, author,
                created_at, updated_at
        """

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, *params)

        return self._row_to_drawing(row) if row else None

    async def delete_drawing(self, drawing_id: UUID) -> bool:
        """Delete drawing.

        Args:
            drawing_id: Drawing UUID

        Returns:
            True if deleted, False if not found
        """
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM drawings WHERE drawing_id = $1",
                drawing_id,
            )

        return result.endswith("1")  # "DELETE 1"

    async def delete_drawings_by_symbol(self, symbol: str) -> int:
        """Delete all drawings for symbol (bulk cleanup).

        Args:
            symbol: Symbol (BTCUSDT)

        Returns:
            Number of deleted drawings
        """
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM drawings WHERE symbol = $1",
                symbol,
            )

        # Extract count from "DELETE N"
        return int(result.split()[-1])

    # ========== Workspaces CRUD ==========

    async def create_workspace(
        self,
        name: str,
        symbol: str,
        timeframe: str,
        layout: dict,
        indicators: list[dict],
        author: Optional[str] = None,
        is_default: bool = False,
        schema_version: int = 1,
    ) -> Workspace:
        """Create new workspace.

        Args:
            name: Workspace name
            symbol: Primary symbol
            timeframe: Primary timeframe
            layout: Panel layout config
            indicators: Indicator configs
            author: Optional author ID
            is_default: Is default workspace for user
            schema_version: Schema version (default: 1)

        Returns:
            Created Workspace
        """
        workspace_id = uuid4()

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO workspaces (
                    workspace_id, name, symbol, timeframe,
                    layout, indicators, schema_version,
                    author, is_default, created_at, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW(), NOW())
                RETURNING
                    workspace_id, name, symbol, timeframe,
                    layout, indicators, schema_version, revision,
                    author, is_default, created_at, updated_at
                """,
                workspace_id,
                name,
                symbol,
                timeframe,
                layout,
                indicators,
                schema_version,
                author,
                is_default,
            )

        return self._row_to_workspace(row)

    async def get_workspace(self, workspace_id: UUID) -> Optional[Workspace]:
        """Get workspace by ID.

        Args:
            workspace_id: Workspace UUID

        Returns:
            Workspace or None
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    workspace_id, name, symbol, timeframe,
                    layout, indicators, schema_version, revision,
                    author, is_default, created_at, updated_at
                FROM workspaces
                WHERE workspace_id = $1
                """,
                workspace_id,
            )

        return self._row_to_workspace(row) if row else None

    async def list_workspaces(self, author: Optional[str] = None) -> list[Workspace]:
        """List all workspaces.

        Args:
            author: Optional filter by author

        Returns:
            List of Workspaces
        """
        if author:
            query = """
                SELECT
                    workspace_id, name, symbol, timeframe,
                    layout, indicators, schema_version, revision,
                    author, is_default, created_at, updated_at
                FROM workspaces
                WHERE author = $1
                ORDER BY is_default DESC, created_at DESC
            """
            params = [author]
        else:
            query = """
                SELECT
                    workspace_id, name, symbol, timeframe,
                    layout, indicators, schema_version, revision,
                    author, is_default, created_at, updated_at
                FROM workspaces
                ORDER BY is_default DESC, created_at DESC
            """
            params = []

        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [self._row_to_workspace(row) for row in rows]

    async def update_workspace(
        self,
        workspace_id: UUID,
        name: Optional[str] = None,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        layout: Optional[dict] = None,
        indicators: Optional[list[dict]] = None,
    ) -> Optional[Workspace]:
        """Update workspace.

        Args:
            workspace_id: Workspace UUID
            name: Optional new name
            symbol: Optional new symbol
            timeframe: Optional new timeframe
            layout: Optional new layout
            indicators: Optional new indicators

        Returns:
            Updated Workspace or None
        """
        updates = []
        params = []
        param_idx = 1

        if name is not None:
            updates.append(f"name = ${param_idx}")
            params.append(name)
            param_idx += 1

        if symbol is not None:
            updates.append(f"symbol = ${param_idx}")
            params.append(symbol)
            param_idx += 1

        if timeframe is not None:
            updates.append(f"timeframe = ${param_idx}")
            params.append(timeframe)
            param_idx += 1

        if layout is not None:
            updates.append(f"layout = ${param_idx}")
            params.append(layout)
            param_idx += 1

        if indicators is not None:
            updates.append(f"indicators = ${param_idx}")
            params.append(indicators)
            param_idx += 1

        if not updates:
            return await self.get_workspace(workspace_id)

        updates.append("revision = revision + 1")
        updates.append("updated_at = NOW()")

        params.append(workspace_id)
        query = f"""
            UPDATE workspaces
            SET {', '.join(updates)}
            WHERE workspace_id = ${param_idx}
            RETURNING
                workspace_id, name, symbol, timeframe,
                layout, indicators, schema_version, revision,
                author, is_default, created_at, updated_at
        """

        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, *params)

        return self._row_to_workspace(row) if row else None

    async def delete_workspace(self, workspace_id: UUID) -> bool:
        """Delete workspace.

        Args:
            workspace_id: Workspace UUID

        Returns:
            True if deleted, False if not found
        """
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM workspaces WHERE workspace_id = $1",
                workspace_id,
            )

        return result.endswith("1")

    # ========== Workspace-Drawing Association ==========

    async def associate_drawing(
        self,
        workspace_id: UUID,
        drawing_id: UUID,
        display_order: int = 0,
    ) -> bool:
        """Associate drawing with workspace.

        Args:
            workspace_id: Workspace UUID
            drawing_id: Drawing UUID
            display_order: Z-order for rendering

        Returns:
            True if associated, False if already exists
        """
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO workspace_drawings (workspace_id, drawing_id, display_order)
                    VALUES ($1, $2, $3)
                    """,
                    workspace_id,
                    drawing_id,
                    display_order,
                )
                return True
            except asyncpg.UniqueViolationError:
                return False

    async def dissociate_drawing(
        self,
        workspace_id: UUID,
        drawing_id: UUID,
    ) -> bool:
        """Remove drawing from workspace.

        Args:
            workspace_id: Workspace UUID
            drawing_id: Drawing UUID

        Returns:
            True if removed, False if not found
        """
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM workspace_drawings
                WHERE workspace_id = $1 AND drawing_id = $2
                """,
                workspace_id,
                drawing_id,
            )

        return result.endswith("1")

    async def get_workspace_drawings(self, workspace_id: UUID) -> list[Drawing]:
        """Get all drawings associated with workspace.

        Args:
            workspace_id: Workspace UUID

        Returns:
            List of Drawings (ordered by display_order)
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    d.drawing_id, d.type, d.symbol, d.workspace_id,
                    d.points, d.style, d.locked, d.hidden,
                    d.schema_version, d.revision, d.author,
                    d.created_at, d.updated_at
                FROM drawings d
                JOIN workspace_drawings wd ON d.drawing_id = wd.drawing_id
                WHERE wd.workspace_id = $1
                ORDER BY wd.display_order ASC
                """,
                workspace_id,
            )

        return [self._row_to_drawing(row) for row in rows]

    # ========== Helper Methods ==========

    def _row_to_drawing(self, row) -> Drawing:
        """Convert asyncpg.Record to Drawing model."""
        return Drawing(
            id=str(row["drawing_id"]),
            type=row["type"],
            symbol=row["symbol"],
            points=[DrawingPoint(**p) for p in row["points"]],
            style=row["style"],
            locked=row["locked"],
            hidden=row["hidden"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_workspace(self, row) -> Workspace:
        """Convert asyncpg.Record to Workspace model."""
        return Workspace(
            id=str(row["workspace_id"]),
            name=row["name"],
            symbol=row["symbol"],
            timeframe=row["timeframe"],
            layout=row["layout"],
            indicators=row["indicators"],
            drawing_ids=[],  # Filled separately via get_workspace_drawings
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
