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
- GET /api/v1/analytics/heatmap — Orderbook Heatmap (Этап 6 / P3-A5)
- GET /api/v1/analytics/orderflow/regime — Market Regime (Этап 6 / P3-A6)
- GET /api/v1/analytics/orderflow/features — Active Features (Этап 6 / P3-A7)
"""

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import ValidationError

from packages.api.aggregation import aggregate_ohlc, parse_interval
from packages.api.models import TradesQueryParams, TradesResponse, OHLCQueryParams, OHLCResponse
from packages.api.websocket import register_websocket_endpoints, live_feed_manager
from packages.api.redis_subscriber import register_redis_subscriber
from packages.storage.parquet_reader import ParquetReader
from packages.monitoring import get_metrics_collector, Timer
from packages.monitoring.worker_metrics import APIMetrics

logger = logging.getLogger(__name__)

# Конфигурация
DATA_DIR = Path("/tmp/bybit-chart-data")  # Переопределяется через env или config


def resolve_time_range(
    start_ts: int | None,
    end_ts: int | None,
    limit: int,
    interval_us: int,
) -> tuple[int, int]:
    """Resolve time range from optional start_ts/end_ts or limit.

    Args:
        start_ts: Optional start timestamp (microseconds)
        end_ts: Optional end timestamp (microseconds)
        limit: Number of intervals to fetch if start_ts/end_ts not provided
        interval_us: Interval duration in microseconds

    Returns:
        Tuple of (start_ts, end_ts) in microseconds
    """
    import time

    if start_ts is not None and end_ts is not None:
        return start_ts, end_ts

    # Use limit to calculate time range from now
    now_us = int(time.time() * 1_000_000)
    lookback_us = limit * interval_us
    return now_us - lookback_us, now_us


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

    # Initialize metrics collector (old general metrics)
    metrics = get_metrics_collector()

    # Initialize API-specific metrics
    api_metrics = APIMetrics()

    @app.get("/health")
    async def health_check():
        """Health check endpoint для monitoring.

        Returns:
            {
                "status": "healthy" | "degraded",
                "timestamp": int,
                "version": "1.0.0",
                "services": {
                    "redis": "connected" | "disconnected",
                    "storage": "ready" | "error"
                }
            }
        """
        import time
        from packages.storage.redis_publisher import get_redis_publisher

        health_status = {
            "status": "healthy",
            "service": "bybit-chart-query-api",
            "timestamp": int(time.time()),
            "version": "1.0.0",
            "services": {}
        }

        # Check Redis connection
        try:
            redis_pub = get_redis_publisher()
            if redis_pub.client:
                redis_pub.client.ping()
                health_status["services"]["redis"] = "connected"
            else:
                health_status["services"]["redis"] = "disconnected"
        except:
            health_status["services"]["redis"] = "disconnected"

        # Check storage
        try:
            if reader_data_dir.exists():
                health_status["services"]["storage"] = "ready"
            else:
                health_status["services"]["storage"] = "error"
                health_status["status"] = "degraded"
        except:
            health_status["services"]["storage"] = "error"
            health_status["status"] = "degraded"

        return JSONResponse(
            status_code=200 if health_status["status"] == "healthy" else 503,
            content=health_status
        )

    @app.get("/metrics", response_class=PlainTextResponse)
    async def prometheus_metrics():
        """Prometheus metrics endpoint.

        Returns:
            Metrics в Prometheus exposition format

        Roadmap §15: metrics для Prometheus scraping.
        """
        # Combine old metrics + new API-specific metrics
        old_metrics = metrics.export_prometheus()
        new_metrics = api_metrics.to_prometheus()
        return old_metrics + "\n" + new_metrics

    # Middleware для request metrics
    @app.middleware("http")
    async def metrics_middleware(request, call_next):
        """Track request metrics."""
        import time
        start_time = time.time()

        api_metrics.http_requests_total.inc()
        metrics.http_requests_total.inc()  # Keep old metrics too

        try:
            response = await call_next(request)

            duration = time.time() - start_time
            api_metrics.http_request_duration_seconds.observe(duration)

            if response.status_code >= 400:
                api_metrics.http_errors_total.inc()
                metrics.http_errors_total.inc()

            return response
        except Exception as exc:
            api_metrics.http_errors_total.inc()
            metrics.http_errors_total.inc()
            raise

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
        limit: int = Query(1000, description="Максимальное количество событий", ge=1, le=10000),
        start_ts: int | None = Query(None, description="Начало диапазона (microseconds)", ge=0),
        end_ts: int | None = Query(None, description="Конец диапазона (microseconds)", ge=0),
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
        # Resolve time range
        if start_ts is None or end_ts is None:
            # Default: last 1 minute of trades
            start_ts, end_ts = resolve_time_range(start_ts, end_ts, limit=1, interval_us=60_000_000)

        # Чтение из Parquet
        try:
            events = reader.read_range(
                symbol=symbol,
                start_ts=start_ts,
                end_ts=end_ts,
                limit=limit,
                event_type=event_type,
            )

            has_more = len(events) == limit

            return TradesResponse(
                symbol=symbol,
                start_ts=start_ts,
                end_ts=end_ts,
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
        interval: str = Query(..., description="Интервал candle (1m, 5m, 15m, 1h, 4h, 1d)"),
        start_ts: int | None = Query(None, description="Начало диапазона (microseconds)", ge=0),
        end_ts: int | None = Query(None, description="Конец диапазона (microseconds)", ge=0),
        limit: int = Query(500, description="Количество последних candles", ge=1, le=5000),
    ):
        """Получить OHLC candles (агрегированные RawTrade).

        Query params:
            - symbol: идентификатор инструмента (BTCUSDT)
            - interval: интервал candle (1m, 5m, 15m, 30m, 1h, 2h, 4h, 1d)
            - start_ts: начало диапазона (microseconds, inclusive) — опционально
            - end_ts: конец диапазона (microseconds, exclusive) — опционально
            - limit: количество последних candles (по умолчанию 500, если не указан start_ts/end_ts)

        Returns:
            200 OK: OHLCResponse с candles
            400 Bad Request: некорректные параметры
            404 Not Found: symbol не существует
            500 Internal Server Error: ошибка чтения данных

        Example 1 (last N candles):
            GET /api/v1/ohlc?symbol=BTCUSDT&interval=1m&limit=100

        Example 2 (time range):
            GET /api/v1/ohlc?symbol=BTCUSDT&start_ts=1786372648000000&end_ts=1786372650000000&interval=1m
        """
        import time

        # Парсинг interval → microseconds
        try:
            interval_us = parse_interval(interval)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=str(exc),
            )

        # Если start_ts/end_ts не указаны, берём последние N candles
        if start_ts is None or end_ts is None:
            end_ts = int(time.time() * 1_000_000)  # текущее время в microseconds
            start_ts = end_ts - (limit * interval_us)  # limit интервалов назад

        # Чтение RawTrade из Parquet
        try:
            read_start = time.time()
            events = reader.read_range(
                symbol=symbol,
                start_ts=start_ts,
                end_ts=end_ts,
                event_type="RawTrade",  # только trades для OHLC
            )
            read_time = (time.time() - read_start) * 1000

            # Агрегация → candles
            agg_start = time.time()
            candles = aggregate_ohlc(events, interval_us)
            agg_time = (time.time() - agg_start) * 1000

            logger.info(
                f"[STEP:API→Parquet→OHLC] {symbol} {interval} read {len(events)} trades in {read_time:.1f}ms "
                f"→ aggregated {len(candles)} candles in {agg_time:.1f}ms"
            )

            # Ограничить до limit последних candles
            if len(candles) > limit:
                candles = candles[-limit:]

            return OHLCResponse(
                symbol=symbol,
                interval=interval,
                start_ts=start_ts,
                end_ts=end_ts,
                candles=candles,
                count=len(candles),
            )

        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=f"Symbol не найден: {symbol}",
            )
        except Exception as exc:
            logger.error(f"[STEP:API→Parquet→OHLC] ERROR: {symbol} {interval} failed: {exc}")
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
        interval: str = Query("1m", description="Интервал (1m, 5m, 15m, 1h, 4h, 1d)"),
        limit: int = Query(100, description="Количество баров", ge=1, le=5000),
        start_ts: int | None = Query(None, description="Начало диапазона (microseconds)", ge=0),
        end_ts: int | None = Query(None, description="Конец диапазона (microseconds)", ge=0),
    ):
        """Получить Delta analytics (buy/sell pressure).

        Roadmap §9.2: Delta = buy_volume - sell_volume по временным окнам.
        """
        from packages.analytics.delta import aggregate_delta_by_interval

        try:
            interval_us = parse_interval(interval)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        # Resolve time range
        start_ts, end_ts = resolve_time_range(start_ts, end_ts, limit, interval_us)

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
        interval: str = Query("1m", description="Интервал (1m, 5m, 15m, 1h, 4h, 1d)"),
        limit: int = Query(100, description="Количество баров", ge=1, le=5000),
        start_ts: int | None = Query(None, description="Начало диапазона (microseconds)", ge=0),
        end_ts: int | None = Query(None, description="Конец диапазона (microseconds)", ge=0),
    ):
        """Получить CVD analytics (Cumulative Volume Delta).

        Roadmap §9.2: CVD = cumsum(Delta), показывает накопленное давление.
        """
        from packages.analytics.cvd import aggregate_cvd_by_interval

        try:
            interval_us = parse_interval(interval)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        start_ts, end_ts = resolve_time_range(start_ts, end_ts, limit, interval_us)

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
        interval: str = Query("1m", description="Интервал (1m, 5m, 15m, 1h, 4h, 1d)"),
        limit: int = Query(100, description="Количество баров", ge=1, le=5000),
        start_ts: int | None = Query(None, description="Начало диапазона (microseconds)", ge=0),
        end_ts: int | None = Query(None, description="Конец диапазона (microseconds)", ge=0),
    ):
        """Получить VWAP analytics (Volume Weighted Average Price).

        Roadmap §9.2: VWAP = Σ(price × volume) / Σ(volume).
        """
        from packages.analytics.vwap import aggregate_vwap_by_interval

        try:
            interval_us = parse_interval(interval)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        start_ts, end_ts = resolve_time_range(start_ts, end_ts, limit, interval_us)

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
        limit: int = Query(60, description="Минут данных", ge=1, le=1440),
        start_ts: int | None = Query(None, description="Начало диапазона (microseconds)", ge=0),
        end_ts: int | None = Query(None, description="Конец диапазона (microseconds)", ge=0),
        price_bin_ticks: int = Query(100, description="Размер ценового bin (ticks)", ge=1),
    ):
        """Получить Volume Profile (распределение объёма по ценам).

        Roadmap §9.2: POC, Value Area, HVN/LVN для определения ключевых уровней.
        """
        from packages.analytics.volume_profile import calculate_volume_profile, find_hvn_lvn

        start_ts, end_ts = resolve_time_range(start_ts, end_ts, limit, 60_000_000)

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
    # Order Flow Endpoints (Roadmap §9: Time & Sales, Footprint)
    # ========================================================================

    @app.get("/api/v1/tape/{symbol}")
    async def get_tape(
        symbol: str,
        limit: int = Query(100, description="Максимум записей", ge=1, le=1000),
        start_ts: int | None = Query(None, description="Начало диапазона (microseconds)", ge=0),
        end_ts: int | None = Query(None, description="Конец диапазона (microseconds)", ge=0),
    ):
        """Получить Time & Sales tape (trade stream).

        Roadmap §9: Time & Sales — поток сделок с aggressor side.

        Query params:
            - symbol: BTCUSDT | ETHUSDT | XRPUSDT
            - start_ts: начало диапазона (microseconds)
            - end_ts: конец диапазона (microseconds)
            - limit: максимум записей (default 100, max 1000)

        Returns:
            {
                "symbol": "BTCUSDT",
                "start_ts": int,
                "end_ts": int,
                "tape": [
                    {
                        "timestamp_us": int,
                        "price_ticks": int,
                        "qty_steps": int,
                        "aggressor_side": "Buy" | "Sell",
                        "trade_id": str
                    },
                    ...
                ],
                "stats": {
                    "total_volume": int,
                    "buy_volume": int,
                    "sell_volume": int,
                    "tape_speed": float,
                    ...
                }
            }
        """
        from packages.analytics.time_and_sales import create_tape_from_trades

        start_ts, end_ts = resolve_time_range(start_ts, end_ts, limit=1, interval_us=60_000_000)

        try:
            events = reader.read_range(
                symbol=symbol,
                start_ts=start_ts,
                end_ts=end_ts,
                event_type="RawTrade",
            )

            tape = create_tape_from_trades(events)
            tape_entries = tape.get_recent(count=limit)
            stats = tape.calculate_tape_stats(window_entries=len(tape.entries))

            return JSONResponse(
                status_code=200,
                content={
                    "symbol": symbol,
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "tape": [e.to_dict() for e in tape_entries],
                    "stats": stats,
                    "count": len(tape_entries),
                },
            )

        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"Symbol не найден: {symbol}")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Ошибка: {exc}")

    @app.get("/api/v1/footprint/{symbol}")
    async def get_footprint(
        symbol: str,
        interval: str = Query("1m", description="Интервал (1m, 5m, 15m, 1h)"),
        limit: int = Query(100, description="Количество свечей", ge=1, le=500),
        start_ts: int | None = Query(None, description="Начало диапазона (microseconds)", ge=0),
        end_ts: int | None = Query(None, description="Конец диапазона (microseconds)", ge=0),
    ):
        """Получить Footprint chart (volume distribution per price level).

        Roadmap §9: Footprint — распределение объёма внутри свечей.

        Query params:
            - symbol: BTCUSDT | ETHUSDT | XRPUSDT
            - start_ts: начало диапазона (microseconds)
            - end_ts: конец диапазона (microseconds)
            - interval: candle interval (1m, 5m, 15m, 30m, 1h, 4h)

        Returns:
            {
                "symbol": "BTCUSDT",
                "interval": "1m",
                "candles": [
                    {
                        "timestamp_us": int,
                        "open_ticks": int,
                        "high_ticks": int,
                        "low_ticks": int,
                        "close_ticks": int,
                        "poc_price": int,
                        "cells": [
                            {
                                "price_ticks": int,
                                "buy_volume": int,
                                "sell_volume": int,
                                "delta": int,
                                "imbalance": float
                            },
                            ...
                        ]
                    },
                    ...
                ]
            }
        """
        from packages.analytics.footprint import FootprintAggregator, compute_footprint_bars
        from contracts.schemas import RawTrade

        try:
            interval_us = parse_interval(interval)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        start_ts, end_ts = resolve_time_range(start_ts, end_ts, limit, interval_us)
        interval_seconds = interval_us // 1_000_000

        try:
            events = reader.read_range(
                symbol=symbol,
                start_ts=start_ts,
                end_ts=end_ts,
                event_type="RawTrade",
            )

            # Конвертировать raw dicts → RawTrade объекты
            # Parquet хранит priceTicks, qtySteps, takerSide (camelCase aliases)
            trades = []
            for row in events:
                if row.get("eventType") != "RawTrade":
                    continue
                try:
                    trades.append(RawTrade(
                        symbol=row.get("symbol", symbol),
                        trade_id=str(row.get("sequence", 0)),
                        sequence=row.get("sequence", 0),
                        exchange_timestamp_ms=row.get("exchangeTimestampMs", 0),
                        outer_timestamp_ms=row.get("outerTimestampMs", 0),
                        receive_timestamp_ms=row.get("receiveTimestampMs", 0),
                        price_ticks=row.get("priceTicks", 0),
                        qty_steps=row.get("qtySteps", 0),
                        taker_side=row.get("takerSide", "Buy"),
                    ))
                except Exception:
                    continue

            # Для отображения в API используем qty_steps напрямую (без конвертации)
            bars = list(compute_footprint_bars(
                iter(trades),
                venue="BYBIT",
                symbol=symbol,
                interval_seconds=interval_seconds,
                tick_size=__import__("decimal").Decimal("1"),
                step_size=__import__("decimal").Decimal("1"),
            ))

            candles = [
                {
                    "interval_start_ms": b.interval_start_ms,
                    "interval_end_ms": b.interval_end_ms,
                    "poc_price": str(b.poc_price) if b.poc_price else None,
                    "total_bid_volume": str(b.total_bid_volume),
                    "total_ask_volume": str(b.total_ask_volume),
                    "overall_imbalance": str(b.overall_imbalance),
                    "level_count": b.level_count,
                    "cells": [
                        {
                            "price": str(level.price),
                            "buy_volume": float(level.bid_volume),
                            "sell_volume": float(level.ask_volume),
                            "delta": float(level.bid_volume - level.ask_volume),
                            "bid_volume": str(level.bid_volume),
                            "ask_volume": str(level.ask_volume),
                            "total_volume": str(level.total_volume),
                            "imbalance": float(level.imbalance),
                            "trade_count": level.trade_count,
                        }
                        for level in sorted(
                            b.levels.values(),
                            key=lambda x: x.price,
                            reverse=True,
                        )
                    ],
                }
                for b in bars
            ]

            return JSONResponse(
                status_code=200,
                content={
                    "symbol": symbol,
                    "interval": interval,
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "candles": candles,
                    "count": len(candles),
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

    # Roadmap §2.1: Redis pub/sub для zero-latency broadcast
    # Если Redis недоступен — fallback на polling (уже в websocket.py)
    register_redis_subscriber(app, live_feed_manager, redis_url="redis://localhost:6379/0")

    # ========================================================================
    # Heatmap Analytics (Roadmap §9.2 Этап 6)
    # ========================================================================

    @app.get("/api/v1/analytics/heatmap")
    async def get_heatmap(
        symbol: str = Query(..., description="Symbol (BTCUSDT)"),
        start_ms: int = Query(..., description="Начало диапазона (milliseconds)", ge=0),
        end_ms: int = Query(..., description="Конец диапазона (milliseconds)", ge=0),
        price_bin_size: int = Query(10, description="Размер price bin (ticks)", ge=1),
        time_interval_ms: int = Query(60000, description="Временной интервал (ms)", ge=1000),
    ):
        """Получить orderbook heatmap tiles (Roadmap §9.2 Этап 6).

        Агрегирует orderbook snapshots в tiles для heatmap visualization.

        Query params:
            - symbol: торговая пара (BTCUSDT)
            - start_ms: начало диапазона (milliseconds)
            - end_ms: конец диапазона (milliseconds)
            - price_bin_size: размер price bin в ticks (default: 10 = 1.0 USDT для BTCUSDT)
            - time_interval_ms: размер временного окна (default: 60000 = 1 minute)

        Returns:
            200 OK: {
                "symbol": "BTCUSDT",
                "tiles": [HeatmapTile, ...],
                "count": int
            }
            400 Bad Request: некорректные параметры
            404 Not Found: symbol не существует или нет orderbook данных

        Example:
            GET /api/v1/analytics/heatmap?symbol=BTCUSDT&start_ms=1786372648000&end_ms=1786372650000
        """
        from packages.analytics.heatmap import compute_heatmap
        from contracts.heatmap import HeatmapQueryParams

        # Валидация параметров
        try:
            params = HeatmapQueryParams(
                start_ms=start_ms,
                end_ms=end_ms,
                price_bin_size=price_bin_size,
                time_interval_ms=time_interval_ms,
            )
            params.validate_range()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        try:
            # Читаем orderbook snapshots из Parquet
            # Конвертируем ms → μs для reader
            events = reader.read_range(
                symbol=symbol,
                start_ts=start_ms * 1000,
                end_ts=end_ms * 1000,
                event_type="RawBookEvent",
            )

            # Фильтруем только snapshots (delta игнорируются)
            snapshots = [e for e in events if e.type == "snapshot"]

            if not snapshots:
                raise HTTPException(
                    status_code=404,
                    detail=f"Нет orderbook snapshots для {symbol} в указанном диапазоне"
                )

            # Вычисляем tiles
            tiles = compute_heatmap(
                book_events=snapshots,
                venue="BYBIT",
                symbol=symbol,
                time_interval_ms=time_interval_ms,
                price_bin_size_ticks=price_bin_size,
            )

            return JSONResponse(
                status_code=200,
                content={
                    "symbol": symbol,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "price_bin_size": price_bin_size,
                    "time_interval_ms": time_interval_ms,
                    "tiles": [tile.model_dump() for tile in tiles],
                    "count": len(tiles),
                },
            )

        except FileNotFoundError:
            raise HTTPException(
                status_code=404,
                detail=f"Symbol не найден или нет orderbook данных: {symbol}"
            )
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Ошибка вычисления heatmap: {exc}"
            )

    # ========================================================================
    # Orderflow Regime & Features API (Roadmap §9.1 Этап 6)
    # ========================================================================

    @app.get("/api/v1/analytics/orderflow/regime")
    async def get_orderflow_regime(
        symbol: str = Query(..., description="Symbol (BTCUSDT)"),
        window_ms: int = Query(300000, description="Analysis window (ms)", ge=60000),
    ):
        """Получить текущий market regime на основе orderflow features (Roadmap §9.1 Этап 6).

        Анализирует все book-derived features и классифицирует текущий режим рынка.

        Query params:
            - symbol: торговая пара (BTCUSDT)
            - window_ms: размер временного окна для анализа (default: 300000 = 5 minutes)

        Returns:
            200 OK: {
                "state": RegimeState,
                "feature_importance": [FeatureImportance, ...],
            }
            404 Not Found: недостаточно данных для анализа

        Regime types:
            - MARKUP: восходящий тренд, buying pressure
            - MARKDOWN: нисходящий тренд, selling pressure
            - ACCUMULATION: низкая волатильность, balanced orderflow
            - DISTRIBUTION: высокая волатильность, imbalanced orderflow
            - NEUTRAL: нет выраженного режима
            - UNKNOWN: недостаточно данных

        Example:
            GET /api/v1/analytics/orderflow/regime?symbol=BTCUSDT&window_ms=300000
        """
        from packages.analytics.regime import RegimeDetector

        try:
            detector = RegimeDetector(symbol=symbol, window_ms=window_ms)

            # TODO: В production читать реальные features из orderflow детекторов
            # Сейчас возвращаем mock для демонстрации API

            import time
            current_ms = int(time.time() * 1000)

            # Mock features для демонстрации
            detector.add_feature("obi", active=True, value=0.5, confidence=0.8, timestamp_ms=current_ms)
            detector.add_feature("ofi", active=True, value=0.3, confidence=0.7, timestamp_ms=current_ms)
            detector.add_feature("walls_bid", active=False, confidence=0.2, timestamp_ms=current_ms)

            analysis = detector.analyze()

            return JSONResponse(
                status_code=200,
                content={
                    "symbol": symbol,
                    "state": {
                        "symbol": analysis.state.symbol,
                        "regime": analysis.state.regime,
                        "regime_confidence": analysis.state.regime_confidence,
                        "features": [f.model_dump() for f in analysis.state.features],
                        "timestamp_ms": analysis.state.timestamp_ms,
                        "window_ms": analysis.state.window_ms,
                    },
                    "feature_importance": [fi.model_dump() for fi in analysis.feature_importance],
                },
            )

        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Ошибка анализа regime: {exc}"
            )

    @app.get("/api/v1/analytics/orderflow/features")
    async def get_orderflow_features(
        symbol: str = Query(..., description="Symbol (BTCUSDT)"),
        active_only: bool = Query(False, description="Только активные features"),
    ):
        """Получить список всех orderflow features (Roadmap §9.1 Этап 6).

        Возвращает состояние всех book-derived детекторов.

        Query params:
            - symbol: торговая пара (BTCUSDT)
            - active_only: фильтр только активных features (default: false)

        Returns:
            200 OK: {
                "symbol": "BTCUSDT",
                "features": [OrderflowFeature, ...],
                "count": int
            }

        Available features:
            - obi: Order Book Imbalance
            - ofi: Order Flow Imbalance
            - absorption: Liquidity Absorption
            - walls_bid/walls_ask: Price Walls
            - pulling_stacking: Order Pulling/Stacking
            - liquidation_cascade: Liquidation Cascades

        Example:
            GET /api/v1/analytics/orderflow/features?symbol=BTCUSDT&active_only=true
        """
        from packages.analytics.regime import RegimeDetector

        try:
            detector = RegimeDetector(symbol=symbol)

            # TODO: В production читать реальные features из live детекторов
            # Сейчас возвращаем mock для демонстрации API

            import time
            current_ms = int(time.time() * 1000)

            # Mock features
            detector.add_feature("obi", active=True, value=0.65, confidence=0.85, timestamp_ms=current_ms,
                               metadata={"bid_volume": 5000, "ask_volume": 3000})
            detector.add_feature("ofi", active=True, value=0.42, confidence=0.78, timestamp_ms=current_ms)
            detector.add_feature("absorption", active=False, confidence=0.25, timestamp_ms=current_ms)
            detector.add_feature("walls_bid", active=True, value=50000, confidence=0.9, timestamp_ms=current_ms,
                               metadata={"side": "bid", "price_level": 50000, "qty": 1000})
            detector.add_feature("pulling_stacking", active=False, confidence=0.15, timestamp_ms=current_ms)
            detector.add_feature("liquidation_cascade", active=False, confidence=0.1, timestamp_ms=current_ms)

            state = detector.compute_regime()
            features = state.features

            if active_only:
                features = [f for f in features if f.active]

            return JSONResponse(
                status_code=200,
                content={
                    "symbol": symbol,
                    "features": [f.model_dump() for f in features],
                    "count": len(features),
                    "timestamp_ms": current_ms,
                },
            )

        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Ошибка чтения features: {exc}"
            )

    return app


# Глобальный app instance для uvicorn
import os
app = create_app(data_dir=os.environ.get("DATA_DIR", DATA_DIR))


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
