"""
Pydantic models для Drawings и Workspaces (Roadmap §11.3, §11.7).

Источник: Roadmap §11 (Frontend analysis workstation)

Server source of truth:
- Drawings: user-drawn lines, shapes, markers
- Workspaces: saved layouts + indicator configs + drawings
- Scripts: Pine Script / strategy code

localStorage только для UI cache (theme, last view).
"""

from datetime import datetime
from typing import Literal, Any
from pydantic import BaseModel, Field


# ========== Drawings ==========


DrawingType = Literal[
    "trendline",
    "ray",
    "horizontal",
    "vertical",
    "rectangle",
    "ellipse",
    "text",
    "channel",
    "fibonacci",
    "anchored-vwap",
    "volume-profile",
    "ruler",
    "risk-reward",
]


class DrawingPoint(BaseModel):
    """Point на графике (timestamp + price)."""

    timestamp_us: int = Field(..., description="Timestamp в microseconds")
    price_ticks: int = Field(..., description="Price в ticks")


class Drawing(BaseModel):
    """Одна drawing (line, shape, marker)."""

    id: str = Field(..., description="Unique ID (UUID)")
    type: DrawingType = Field(..., description="Тип drawing")
    symbol: str = Field(..., description="Symbol (BTCUSDT)")
    points: list[DrawingPoint] = Field(..., description="Anchor points (1+ точки)")
    style: dict[str, Any] = Field(
        default_factory=dict,
        description="Стиль (color, width, dash, text content)",
    )
    locked: bool = Field(False, description="Locked (не редактируется)")
    hidden: bool = Field(False, description="Hidden (не показывается)")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DrawingListResponse(BaseModel):
    """Response для GET /api/v1/drawings."""

    symbol: str
    drawings: list[Drawing]
    count: int


class CreateDrawingRequest(BaseModel):
    """Request для POST /api/v1/drawings."""

    type: DrawingType
    symbol: str
    points: list[DrawingPoint]
    style: dict[str, Any] = Field(default_factory=dict)


class UpdateDrawingRequest(BaseModel):
    """Request для PUT /api/v1/drawings/{drawing_id}."""

    points: list[DrawingPoint] | None = None
    style: dict[str, Any] | None = None
    locked: bool | None = None
    hidden: bool | None = None


# ========== Workspaces ==========


class Workspace(BaseModel):
    """Workspace — saved layout + indicators + drawings."""

    id: str = Field(..., description="Unique ID (UUID)")
    name: str = Field(..., description="Workspace name")
    symbol: str = Field(..., description="Primary symbol (BTCUSDT)")
    timeframe: str = Field(..., description="Primary timeframe (15m)")
    layout: dict[str, Any] = Field(
        default_factory=dict,
        description="Panel layout (sizes, visibility, tabs)",
    )
    indicators: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Indicator configs (type, params, enabled)",
    )
    drawing_ids: list[str] = Field(
        default_factory=list,
        description="Associated drawing IDs",
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class WorkspaceListResponse(BaseModel):
    """Response для GET /api/v1/workspaces."""

    workspaces: list[Workspace]
    count: int


class CreateWorkspaceRequest(BaseModel):
    """Request для POST /api/v1/workspaces."""

    name: str
    symbol: str
    timeframe: str
    layout: dict[str, Any] = Field(default_factory=dict)
    indicators: list[dict[str, Any]] = Field(default_factory=list)
    drawing_ids: list[str] = Field(default_factory=list)


class UpdateWorkspaceRequest(BaseModel):
    """Request для PUT /api/v1/workspaces/{workspace_id}."""

    name: str | None = None
    symbol: str | None = None
    timeframe: str | None = None
    layout: dict[str, Any] | None = None
    indicators: list[dict[str, Any]] | None = None
    drawing_ids: list[str] | None = None
