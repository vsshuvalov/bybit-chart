"""
FastAPI приложение для Query API (Stage 3 / P3-S3-002).

Источник: Roadmap §7 (Query & Aggregation), §4 (FastAPI stack)
Архитектура: REST endpoints → ParquetReader → Parquet files

Endpoints:
- GET /health — health check
- GET /api/v1/symbols — список доступных symbols
- GET /api/v1/trades — чтение RawTrade/BookCheckpoint из Parquet (P3-S3-003)
- GET /api/v1/ohlc — OHLC aggregation (P3-S3-004)
- GET /api/v1/analytics/delta — Delta analytics (Этап 3 / P3-A1)
- GET /api/v1/analytics/cvd — CVD analytics (Этап 3 / P3-A2)
- GET /api/v1/analytics/vwap — VWAP analytics (Этап 3 / P3-A3)
- GET /api/v1/analytics/volume-profile — Volume Profile (Этап 3 / P3-A4)
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from packages.api.aggregation import aggregate_ohlc, parse_interval
from packages.api.models import TradesQueryParams, TradesResponse, OHLCQueryParams, OHLCResponse
from packages.api.websocket import register_websocket_endpoints
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

    # CORS middleware для frontend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # В production: указать конкретные origins
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
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

    @app.get("/api/v1/trades", response_model=TradesResponse)
    async def get_trades(
        symbol: str = Query(..., description="Symbol (BTCUSDT)"),
        start_ts: int = Query(..., description="Начало диапазона (microseconds)", ge=0),
        end_ts: int = Query(..., description="Конец диапазона (microseconds)", ge=0),
        limit: int = Query(1000, description="Максимальное количество событий", ge=1, le=10000),
        event_type: str | None = Query(None, description="Фильтр по eventType"),
    ):
        """Получить события (RawTrade/BookCheckpoint) из Parquet.

        Query params:
            - symbol: идентификатор инструмента (BTCUSDT)
            - start_ts: начало диапазона (microseconds, inclusive)
            - end_ts: конец диапазона (microseconds, exclusive)
            - limit: максимальное количество событий (default 1000, max 10000)
            - event_type: фильтр по eventType (RawTrade, BookCheckpoint)

        Returns:
            200 OK: TradesResponse с событиями
            400 Bad Request: некорректные параметры
            404 Not Found: symbol не существует
            500 Internal Server Error: ошибка чтения данных

        Example:
            GET /api/v1/trades?symbol=BTCUSDT&start_ts=1786372648000000&end_ts=1786372650000000&limit=100
            Response: {
                "symbol": "BTCUSDT",
                "start_ts": 1786372648000000,
                "end_ts": 1786372650000000,
                "events": [{...}, {...}],
                "count": 100,
                "has_more": true
            }
        """
        # Валидация через Pydantic
        try:
            params = TradesQueryParams(
                symbol=symbol,
                start_ts=start_ts,
                end_ts=end_ts,
                limit=limit,
                event_type=event_type,
            )
        except ValidationError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Некорректные параметры: {exc.errors()}",
            )

        # Чтение из Parquet
        try:
            events = reader.read_range(
                symbol=params.symbol,
                start_ts=params.start_ts,
                end_ts=params.end_ts,
                limit=params.limit,
                event_type=params.event_type,
            )

            has_more = len(events) == params.limit

            return TradesResponse(
                symbol=params.symbol,
                start_ts=params.start_ts,
                end_ts=params.end_ts,
                events=events,
                count=len(events),
                has_more=has_more,
            )

        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=f"Symbol не найден: {params.symbol}",
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Ошибка чтения данных: {exc}",
            )

    @app.get("/api/v1/ohlc", response_model=OHLCResponse)
    async def get_ohlc(
        symbol: str = Query(..., description="Symbol (BTCUSDT)"),
        start_ts: int = Query(..., description="Начало диапазона (microseconds)", ge=0),
        end_ts: int = Query(..., description="Конец диапазона (microseconds)", ge=0),
        interval: str = Query(..., description="Интервал candle (1m, 5m, 15m, 1h, 4h, 1d)"),
    ):
        """Получить OHLC candles (агрегированные RawTrade).

        Query params:
            - symbol: идентификатор инструмента (BTCUSDT)
            - start_ts: начало диапазона (microseconds, inclusive)
            - end_ts: конец диапазона (microseconds, exclusive)
            - interval: интервал candle (1m, 5m, 15m, 30m, 1h, 2h, 4h, 1d)

        Returns:
            200 OK: OHLCResponse с candles
            400 Bad Request: некорректные параметры
            404 Not Found: symbol не существует
            500 Internal Server Error: ошибка чтения данных

        Example:
            GET /api/v1/ohlc?symbol=BTCUSDT&start_ts=1786372648000000&end_ts=1786372650000000&interval=1m
            Response: {
                "symbol": "BTCUSDT",
                "interval": "1m",
                "candles": [
                    {
                        "timestamp_us": 1786372620000000,
                        "open_ticks": 647780,
                        "high_ticks": 647850,
                        "low_ticks": 647750,
                        "close_ticks": 647800,
                        "volume_steps": 1500,
                        "trade_count": 45
                    }
                ],
                "count": 1
            }
        """
        # Валидация через Pydantic
        try:
            params = OHLCQueryParams(
                symbol=symbol,
                start_ts=start_ts,
                end_ts=end_ts,
                interval=interval,
            )
        except ValidationError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Некорректные параметры: {exc.errors()}",
            )

        # Парсинг interval → microseconds
        try:
            interval_us = parse_interval(params.interval)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=str(exc),
            )

        # Чтение RawTrade из Parquet
        try:
            events = reader.read_range(
                symbol=params.symbol,
                start_ts=params.start_ts,
                end_ts=params.end_ts,
                event_type="RawTrade",  # только trades для OHLC
            )

            # Агрегация → candles
            candles = aggregate_ohlc(events, interval_us)

            return OHLCResponse(
                symbol=params.symbol,
                interval=params.interval,
                start_ts=params.start_ts,
                end_ts=params.end_ts,
                candles=candles,
                count=len(candles),
            )

        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=f"Symbol не найден: {params.symbol}",
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Ошибка чтения данных: {exc}",
            )

    # ========================================================================
    # Analytics Endpoints (Этап 3)
    # ========================================================================

    @app.get("/api/v1/analytics/delta")
    async def get_delta(
        symbol: str = Query(..., description="Symbol (BTCUSDT)"),
        start_ts: int = Query(..., description="Начало диапазона (microseconds)", ge=0),
        end_ts: int = Query(..., description="Конец диапазона (microseconds)", ge=0),
        interval: str = Query(..., description="Интервал (1m, 5m, 15m, 1h, 4h, 1d)"),
    ):
        """Получить Delta analytics (buy/sell pressure).

        Roadmap §9.2: Delta = buy_volume - sell_volume по временным окнам.
        """
        from packages.analytics.delta import aggregate_delta_by_interval

        try:
            interval_us = parse_interval(interval)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        try:
            events = reader.read_range(
                symbol=symbol,
                start_ts=start_ts,
                end_ts=end_ts,
                event_type="RawTrade",
            )

            delta_bars = aggregate_delta_by_interval(events, interval_us)

            return JSONResponse(
                status_code=200,
                content={
                    "symbol": symbol,
                    "interval": interval,
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "bars": delta_bars,
                    "count": len(delta_bars),
                },
            )

        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Symbol не найден: {symbol}")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Ошибка: {exc}")

    @app.get("/api/v1/analytics/cvd")
    async def get_cvd(
        symbol: str = Query(..., description="Symbol (BTCUSDT)"),
        start_ts: int = Query(..., description="Начало диапазона (microseconds)", ge=0),
        end_ts: int = Query(..., description="Конец диапазона (microseconds)", ge=0),
        interval: str = Query(..., description="Интервал (1m, 5m, 15m, 1h, 4h, 1d)"),
    ):
        """Получить CVD analytics (Cumulative Volume Delta).

        Roadmap §9.2: CVD = cumsum(Delta), показывает накопленное давление.
        """
        from packages.analytics.cvd import aggregate_cvd_by_interval

        try:
            interval_us = parse_interval(interval)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        try:
            events = reader.read_range(
                symbol=symbol,
                start_ts=start_ts,
                end_ts=end_ts,
                event_type="RawTrade",
            )

            cvd_bars = aggregate_cvd_by_interval(events, interval_us)

            return JSONResponse(
                status_code=200,
                content={
                    "symbol": symbol,
                    "interval": interval,
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "bars": cvd_bars,
                    "count": len(cvd_bars),
                },
            )

        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Symbol не найден: {symbol}")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Ошибка: {exc}")

    @app.get("/api/v1/analytics/vwap")
    async def get_vwap(
        symbol: str = Query(..., description="Symbol (BTCUSDT)"),
        start_ts: int = Query(..., description="Начало диапазона (microseconds)", ge=0),
        end_ts: int = Query(..., description="Конец диапазона (microseconds)", ge=0),
        interval: str = Query(..., description="Интервал (1m, 5m, 15m, 1h, 4h, 1d)"),
    ):
        """Получить VWAP analytics (Volume Weighted Average Price).

        Roadmap §9.2: VWAP = Σ(price × volume) / Σ(volume).
        """
        from packages.analytics.vwap import aggregate_vwap_by_interval

        try:
            interval_us = parse_interval(interval)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        try:
            events = reader.read_range(
                symbol=symbol,
                start_ts=start_ts,
                end_ts=end_ts,
                event_type="RawTrade",
            )

            vwap_bars = aggregate_vwap_by_interval(events, interval_us)

            return JSONResponse(
                status_code=200,
                content={
                    "symbol": symbol,
                    "interval": interval,
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "bars": vwap_bars,
                    "count": len(vwap_bars),
                },
            )

        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Symbol не найден: {symbol}")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Ошибка: {exc}")

    @app.get("/api/v1/analytics/volume-profile")
    async def get_volume_profile(
        symbol: str = Query(..., description="Symbol (BTCUSDT)"),
        start_ts: int = Query(..., description="Начало диапазона (microseconds)", ge=0),
        end_ts: int = Query(..., description="Конец диапазона (microseconds)", ge=0),
        price_bin_ticks: int = Query(100, description="Размер ценового bin (ticks)", ge=1),
    ):
        """Получить Volume Profile (распределение объёма по ценам).

        Roadmap §9.2: POC, Value Area, HVN/LVN для определения ключевых уровней.
        """
        from packages.analytics.volume_profile import calculate_volume_profile, find_hvn_lvn

        try:
            events = reader.read_range(
                symbol=symbol,
                start_ts=start_ts,
                end_ts=end_ts,
                event_type="RawTrade",
            )

            profile = calculate_volume_profile(events, price_bin_ticks)
            hvn_lvn = find_hvn_lvn(profile)

            return JSONResponse(
                status_code=200,
                content={
                    "symbol": symbol,
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "price_bin_ticks": price_bin_ticks,
                    "profile": profile,
                    "hvn_lvn": hvn_lvn,
                },
            )

        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Symbol не найден: {symbol}")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Ошибка: {exc}")

    # ========================================================================
    # WebSocket Live Feed (Roadmap §2.1)
    # ========================================================================

    # Регистрируем WebSocket endpoints
    register_websocket_endpoints(app, reader)

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
