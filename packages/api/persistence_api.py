"""
REST API endpoints для Drawings и Workspaces (Roadmap §11.3, §11.7).

Endpoints:
- GET    /api/v1/drawings?symbol={symbol}          - List drawings
- POST   /api/v1/drawings                          - Create drawing
- GET    /api/v1/drawings/{drawing_id}             - Get drawing
- PUT    /api/v1/drawings/{drawing_id}             - Update drawing
- DELETE /api/v1/drawings/{drawing_id}             - Delete drawing

- GET    /api/v1/workspaces                        - List workspaces
- POST   /api/v1/workspaces                        - Create workspace
- GET    /api/v1/workspaces/{workspace_id}         - Get workspace
- PUT    /api/v1/workspaces/{workspace_id}         - Update workspace
- DELETE /api/v1/workspaces/{workspace_id}         - Delete workspace
- GET    /api/v1/workspaces/{workspace_id}/drawings - Get workspace drawings
"""

from uuid import UUID
from fastapi import APIRouter, HTTPException, Query as QueryParam
from packages.api.persistence_models import (
    Drawing,
    DrawingListResponse,
    CreateDrawingRequest,
    UpdateDrawingRequest,
    Workspace,
    WorkspaceListResponse,
    CreateWorkspaceRequest,
    UpdateWorkspaceRequest,
)
from packages.api.persistence_postgresql import PostgreSQLPersistence

# Router
persistence_router = APIRouter(prefix="/api/v1", tags=["persistence"])

# Global persistence instance (initialized in app startup)
_persistence: PostgreSQLPersistence | None = None


def set_persistence(persistence: PostgreSQLPersistence):
    """Set global persistence instance (called from app.py startup)."""
    global _persistence
    _persistence = persistence


def get_persistence() -> PostgreSQLPersistence:
    """Get persistence instance or raise error."""
    if _persistence is None:
        raise HTTPException(status_code=500, detail="Persistence not initialized")
    return _persistence


# ========== Drawings Endpoints ==========


@persistence_router.get("/drawings", response_model=DrawingListResponse)
async def list_drawings(
    symbol: str = QueryParam(..., description="Symbol (BTCUSDT)"),
    include_hidden: bool = QueryParam(False, description="Include hidden drawings"),
    workspace_id: str | None = QueryParam(None, description="Filter by workspace UUID"),
):
    """List all drawings for symbol.

    Returns drawings with schemaVersion and revision tracking (§11.3).
    """
    persistence = get_persistence()

    workspace_uuid = UUID(workspace_id) if workspace_id else None
    drawings = await persistence.list_drawings(
        symbol=symbol,
        include_hidden=include_hidden,
        workspace_id=workspace_uuid,
    )

    return DrawingListResponse(
        symbol=symbol,
        drawings=drawings,
        count=len(drawings),
    )


@persistence_router.post("/drawings", response_model=Drawing, status_code=201)
async def create_drawing(request: CreateDrawingRequest):
    """Create new drawing.

    Server persistence with schemaVersion tracking (§11.3, §11.7).
    localStorage is NOT the source of truth.
    """
    persistence = get_persistence()

    drawing = await persistence.create_drawing(
        type=request.type,
        symbol=request.symbol,
        points=request.points,
        style=request.style,
        author="system",  # TODO: get from auth context
        schema_version=1,
    )

    return drawing


@persistence_router.get("/drawings/{drawing_id}", response_model=Drawing)
async def get_drawing(drawing_id: str):
    """Get drawing by ID."""
    persistence = get_persistence()

    try:
        drawing_uuid = UUID(drawing_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    drawing = await persistence.get_drawing(drawing_uuid)
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    return drawing


@persistence_router.put("/drawings/{drawing_id}", response_model=Drawing)
async def update_drawing(drawing_id: str, request: UpdateDrawingRequest):
    """Update drawing.

    Increments revision counter on every update (§11.3).
    """
    persistence = get_persistence()

    try:
        drawing_uuid = UUID(drawing_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    drawing = await persistence.update_drawing(
        drawing_id=drawing_uuid,
        points=request.points,
        style=request.style,
        locked=request.locked,
        hidden=request.hidden,
    )

    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    return drawing


@persistence_router.delete("/drawings/{drawing_id}", status_code=204)
async def delete_drawing(drawing_id: str):
    """Delete drawing permanently."""
    persistence = get_persistence()

    try:
        drawing_uuid = UUID(drawing_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    deleted = await persistence.delete_drawing(drawing_uuid)
    if not deleted:
        raise HTTPException(status_code=404, detail="Drawing not found")


# ========== Workspaces Endpoints ==========


@persistence_router.get("/workspaces", response_model=WorkspaceListResponse)
async def list_workspaces(
    author: str | None = QueryParam(None, description="Filter by author"),
):
    """List all workspaces.

    Server persistence (§11.7). localStorage is only for UI cache.
    """
    persistence = get_persistence()

    workspaces = await persistence.list_workspaces(author=author)

    return WorkspaceListResponse(
        workspaces=workspaces,
        count=len(workspaces),
    )


@persistence_router.post("/workspaces", response_model=Workspace, status_code=201)
async def create_workspace(request: CreateWorkspaceRequest):
    """Create new workspace.

    Workspace contains:
    - layout: panel visibility, sizes, tabs
    - indicators: type, params, enabled
    - drawing_ids: associated drawings
    """
    persistence = get_persistence()

    workspace = await persistence.create_workspace(
        name=request.name,
        symbol=request.symbol,
        timeframe=request.timeframe,
        layout=request.layout,
        indicators=request.indicators,
        author="system",  # TODO: get from auth context
        is_default=False,
        schema_version=1,
    )

    # Associate drawings
    for drawing_id in request.drawing_ids:
        try:
            drawing_uuid = UUID(drawing_id)
            await persistence.associate_drawing(
                workspace_id=UUID(workspace.id),
                drawing_id=drawing_uuid,
            )
        except ValueError:
            pass  # Skip invalid UUIDs

    return workspace


@persistence_router.get("/workspaces/{workspace_id}", response_model=Workspace)
async def get_workspace(workspace_id: str):
    """Get workspace by ID."""
    persistence = get_persistence()

    try:
        workspace_uuid = UUID(workspace_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    workspace = await persistence.get_workspace(workspace_uuid)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Get associated drawing IDs
    drawings = await persistence.get_workspace_drawings(workspace_uuid)
    workspace.drawing_ids = [d.id for d in drawings]

    return workspace


@persistence_router.put("/workspaces/{workspace_id}", response_model=Workspace)
async def update_workspace(workspace_id: str, request: UpdateWorkspaceRequest):
    """Update workspace.

    Increments revision counter on every update (§11.7).
    """
    persistence = get_persistence()

    try:
        workspace_uuid = UUID(workspace_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    workspace = await persistence.update_workspace(
        workspace_id=workspace_uuid,
        name=request.name,
        symbol=request.symbol,
        timeframe=request.timeframe,
        layout=request.layout,
        indicators=request.indicators,
    )

    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Update drawing associations
    if request.drawing_ids is not None:
        # Remove all existing associations
        existing_drawings = await persistence.get_workspace_drawings(workspace_uuid)
        for drawing in existing_drawings:
            await persistence.dissociate_drawing(workspace_uuid, UUID(drawing.id))

        # Add new associations
        for drawing_id in request.drawing_ids:
            try:
                drawing_uuid = UUID(drawing_id)
                await persistence.associate_drawing(workspace_uuid, drawing_uuid)
            except ValueError:
                pass

    # Get updated drawing IDs
    drawings = await persistence.get_workspace_drawings(workspace_uuid)
    workspace.drawing_ids = [d.id for d in drawings]

    return workspace


@persistence_router.delete("/workspaces/{workspace_id}", status_code=204)
async def delete_workspace(workspace_id: str):
    """Delete workspace permanently."""
    persistence = get_persistence()

    try:
        workspace_uuid = UUID(workspace_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    deleted = await persistence.delete_workspace(workspace_uuid)
    if not deleted:
        raise HTTPException(status_code=404, detail="Workspace not found")


@persistence_router.get(
    "/workspaces/{workspace_id}/drawings",
    response_model=DrawingListResponse,
)
async def get_workspace_drawings(workspace_id: str):
    """Get all drawings associated with workspace.

    Returns drawings ordered by display_order (z-order).
    """
    persistence = get_persistence()

    try:
        workspace_uuid = UUID(workspace_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    workspace = await persistence.get_workspace(workspace_uuid)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    drawings = await persistence.get_workspace_drawings(workspace_uuid)

    return DrawingListResponse(
        symbol=workspace.symbol,
        drawings=drawings,
        count=len(drawings),
    )
