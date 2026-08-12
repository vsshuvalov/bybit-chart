"""
In-memory storage для Drawings и Workspaces (Roadmap §11.7).

Production: заменить на PostgreSQL tables.
Dev/Test: in-memory dict для быстрого прототипирования.
"""

from datetime import datetime
from typing import Dict
from packages.api.persistence_models import Drawing, Workspace

# In-memory stores
_drawings: Dict[str, Drawing] = {}
_workspaces: Dict[str, Workspace] = {}


# ========== Drawings CRUD ==========


def create_drawing(drawing: Drawing) -> Drawing:
    """Создать drawing."""
    drawing.created_at = datetime.utcnow()
    drawing.updated_at = datetime.utcnow()
    _drawings[drawing.id] = drawing
    return drawing


def get_drawing(drawing_id: str) -> Drawing | None:
    """Получить drawing по ID."""
    return _drawings.get(drawing_id)


def list_drawings(symbol: str) -> list[Drawing]:
    """Получить все drawings для symbol."""
    return [d for d in _drawings.values() if d.symbol == symbol and not d.hidden]


def update_drawing(drawing_id: str, updates: dict) -> Drawing | None:
    """Обновить drawing."""
    drawing = _drawings.get(drawing_id)
    if not drawing:
        return None

    for key, value in updates.items():
        if value is not None and hasattr(drawing, key):
            setattr(drawing, key, value)

    drawing.updated_at = datetime.utcnow()
    return drawing


def delete_drawing(drawing_id: str) -> bool:
    """Удалить drawing."""
    if drawing_id in _drawings:
        del _drawings[drawing_id]
        return True
    return False


# ========== Workspaces CRUD ==========


def create_workspace(workspace: Workspace) -> Workspace:
    """Создать workspace."""
    workspace.created_at = datetime.utcnow()
    workspace.updated_at = datetime.utcnow()
    _workspaces[workspace.id] = workspace
    return workspace


def get_workspace(workspace_id: str) -> Workspace | None:
    """Получить workspace по ID."""
    return _workspaces.get(workspace_id)


def list_workspaces() -> list[Workspace]:
    """Получить все workspaces."""
    return list(_workspaces.values())


def update_workspace(workspace_id: str, updates: dict) -> Workspace | None:
    """Обновить workspace."""
    workspace = _workspaces.get(workspace_id)
    if not workspace:
        return None

    for key, value in updates.items():
        if value is not None and hasattr(workspace, key):
            setattr(workspace, key, value)

    workspace.updated_at = datetime.utcnow()
    return workspace


def delete_workspace(workspace_id: str) -> bool:
    """Удалить workspace."""
    if workspace_id in _workspaces:
        del _workspaces[workspace_id]
        return True
    return False
