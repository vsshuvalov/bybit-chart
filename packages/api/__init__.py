# packages/api — REST API для Query (Stage 3)
# Источник: Roadmap §7, §4
#
# FastAPI endpoints:
#   GET /health              health check
#   GET /api/v1/symbols      список доступных symbols
#   GET /api/v1/trades       чтение RawTrade из Parquet

from packages.api.app import create_app, app

__all__ = ["create_app", "app"]
