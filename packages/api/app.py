"""
FastAPI приложение для Query API (Stage 3 / P3-S3-002).

Источник: Roadmap §7 (Query & Aggregation), §4 (FastAPI stack)
Архитектура: REST endpoints → ParquetReader → Parquet files

Endpoints:
- GET /health — health check
- GET /api/v1/symbols — список доступных symbols
- GET /api/v1/trades — чтение RawTrade из Parquet (P3-S3-003)
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from packages.storage.parquet_reader import ParquetReader

# Конфигурация
DATA_DIR = Path("/tmp/bybit-chart-data")  # Переопределяется через env или config


def create_app(data_dir: Path | str | None = None) -> FastAPI:
    """Создать FastAPI приложение.

    Args:
        data_dir: базовый каталог с Parquet данными (default: DATA_DIR)

    Returns:
        Настроенное FastAPI приложение
    """
    app = FastAPI(
        title="Bybit Chart Query API",
        description="REST API для чтения Parquet сегментов с RawTrade/BookCheckpoint",
        version="0.1.0",
    )

    # Инициализация ParquetReader
    reader_data_dir = Path(data_dir) if data_dir else DATA_DIR
    reader = ParquetReader(reader_data_dir)

    @app.get("/health")
    async def health_check():
        """Health check endpoint.

        Returns:
            200 OK с статусом приложения
        """
        return JSONResponse(
            status_code=200,
            content={
                "status": "healthy",
                "service": "bybit-chart-query-api",
                "version": "0.1.0",
            },
        )

    @app.get("/api/v1/symbols")
    async def list_symbols():
        """Получить список доступных symbols.

        Returns:
            200 OK: {symbols: ["BTCUSDT", "ETHUSDT"]}
            500 Internal Server Error: ошибка чтения данных

        Example:
            GET /api/v1/symbols
            Response: {"symbols": ["BTCUSDT"], "count": 1}
        """
        try:
            symbols = reader.list_symbols()
            return JSONResponse(
                status_code=200,
                content={
                    "symbols": symbols,
                    "count": len(symbols),
                },
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Ошибка чтения списка symbols: {exc}",
            )

    return app


# Глобальный app instance для uvicorn
app = create_app()


if __name__ == "__main__":
    import uvicorn

    # Для локальной разработки
    uvicorn.run(
        "packages.api.app:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_level="info",
    )
