"""
Тесты package contracts и packages/numeric.
Источник: Roadmap §5.2, §5.6, §6.6; all-modules-data-persistence-architecture-changes.md §3

Acceptance criteria (P1-S1-001):
- Round-trip: int64/Decimal → model → JSON → model без потери точности
- Все поля RawEventEnvelope из §5.2 Roadmap присутствуют
- turnoverQuote отсутствует как поле RawTrade
- Backward-compatibility: старые поля читаются новой схемой
- Нет float в persistent schemas
- Нормализация side ликвидаций: Buy→Long→Sell, Sell→Short→Buy
"""

import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

# Добавляем корень проекта в path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from contracts.schemas import (
    TakerSide, FeedKind, GapReason, GapRecoverability, EventType,
    LiquidatedPositionSide,
    RawTrade, RawBookLevel, RawBookEvent, RawRpiBookLevel, RawRpiBookEvent,
    BookCheckpoint, RawLiquidation, GapMarker, RawEventEnvelope,
)
from packages.numeric.primitives import (
    price_ticks_from_str, qty_steps_from_str, decimal128_from_str,
    validate_price_ticks, validate_qty_steps,
    PRICE_TICKS_MAX, QTY_STEPS_MAX,
)


# ===========================================================================
# packages/numeric — примитивы
# ===========================================================================

class TestPriceTicks:
    def test_from_str_valid(self):
        assert price_ticks_from_str("1000000") == 1000000

    def test_from_str_large(self):
        # int64 max
        assert price_ticks_from_str(str(PRICE_TICKS_MAX)) == PRICE_TICKS_MAX

    def test_from_str_rejects_float(self):
        with pytest.raises(TypeError):
            price_ticks_from_str(1.5)  # type: ignore

    def test_from_str_rejects_int(self):
        # защита: требуем str, не int
        with pytest.raises(TypeError):
            price_ticks_from_str(1000)  # type: ignore

    def test_from_str_rejects_negative(self):
        with pytest.raises(ValueError):
            price_ticks_from_str("-1")

    def test_from_str_rejects_overflow(self):
        with pytest.raises(ValueError):
            price_ticks_from_str(str(PRICE_TICKS_MAX + 1))

    def test_validate_positive(self):
        assert validate_price_ticks(100) == 100

    def test_validate_rejects_zero(self):
        with pytest.raises(ValueError):
            validate_price_ticks(0)

    def test_validate_rejects_float(self):
        with pytest.raises(TypeError):
            validate_price_ticks(1.0)  # type: ignore

    def test_validate_rejects_bool(self):
        with pytest.raises(TypeError):
            validate_price_ticks(True)  # type: ignore


class TestQtySteps:
    def test_from_str_valid(self):
        assert qty_steps_from_str("5000") == 5000

    def test_from_str_rejects_float(self):
        with pytest.raises(TypeError):
            qty_steps_from_str(5.0)  # type: ignore

    def test_validate_positive(self):
        assert validate_qty_steps(1) == 1

    def test_validate_rejects_zero(self):
        with pytest.raises(ValueError):
            validate_qty_steps(0)


class TestDecimal128:
    def test_from_str_valid(self):
        d = decimal128_from_str("65000.50")
        assert d == Decimal("65000.50")

    def test_precision_preserved(self):
        """Точность не теряется в отличие от float."""
        d = decimal128_from_str("0.1")
        # Decimal("0.1") точен; float 0.1 нет
        assert str(d) == "0.1"

    def test_rejects_float(self):
        with pytest.raises(TypeError):
            decimal128_from_str(65000.5)  # type: ignore

    def test_rejects_int(self):
        with pytest.raises(TypeError):
            decimal128_from_str(65000)  # type: ignore

    def test_rejects_nan(self):
        with pytest.raises(ValueError):
            decimal128_from_str("NaN")

    def test_rejects_inf(self):
        with pytest.raises(ValueError):
            decimal128_from_str("Inf")


# ===========================================================================
# contracts/schemas — RawTrade
# ===========================================================================

TRADE_PAYLOAD = {
    "symbol": "BTCUSDT",
    "tradeId": "2290000000001234567",
    "sequence": "1234567890",
    "exchangeTimestampMs": "1691636400000",
    "outerTimestampMs": "1691636400050",
    "receiveTimestampMs": "1691636400055",
    "priceTicks": "6500000",      # int64 как строка — wire-format
    "qtySteps": "1000",
    "takerSide": "Buy",
    "isBlockTrade": False,
    "isRpiTrade": False,
}


class TestRawTrade:
    def test_parse_valid(self):
        t = RawTrade(**TRADE_PAYLOAD)
        assert t.price_ticks == 6500000
        assert t.qty_steps == 1000
        assert t.taker_side == TakerSide.BUY
        assert t.symbol == "BTCUSDT"

    def test_unique_key(self):
        t = RawTrade(**TRADE_PAYLOAD)
        assert t.unique_key() == "BYBIT:linear:BTCUSDT:2290000000001234567"

    def test_no_turnover_quote_field(self):
        """turnoverQuote отсутствует — биржа его не присылает."""
        t = RawTrade(**TRADE_PAYLOAD)
        assert not hasattr(t, "turnover_quote")
        assert "turnoverQuote" not in type(t).model_fields

    def test_rejects_float_price(self):
        bad = {**TRADE_PAYLOAD, "priceTicks": 65000.5}
        with pytest.raises(Exception):
            RawTrade(**bad)

    def test_rejects_negative_price(self):
        bad = {**TRADE_PAYLOAD, "priceTicks": "-1"}
        with pytest.raises(Exception):
            RawTrade(**bad)

    def test_round_trip_json(self):
        """int64 строка → model → JSON → model: точность не теряется."""
        t = RawTrade(**TRADE_PAYLOAD)
        raw_json = t.model_dump_json(by_alias=True)
        data = json.loads(raw_json)
        t2 = RawTrade(**data)
        assert t2.price_ticks == t.price_ticks
        assert t2.qty_steps == t.qty_steps
        assert t2.trade_id == t.trade_id

    def test_sell_side(self):
        payload = {**TRADE_PAYLOAD, "takerSide": "Sell"}
        t = RawTrade(**payload)
        assert t.taker_side == TakerSide.SELL

    def test_large_int64_trade_id_preserved(self):
        """Большой int64 trade_id не теряет точность."""
        large_id = "9223372036854775807"  # int64 max
        payload = {**TRADE_PAYLOAD, "tradeId": large_id}
        t = RawTrade(**payload)
        assert t.trade_id == large_id


# ===========================================================================
# contracts/schemas — RawBookEvent
# ===========================================================================

class TestRawBookEvent:
    def _make(self, depth=50, type_="snapshot"):
        return {
            "symbol": "BTCUSDT",
            "depth": depth,
            "connectionEpoch": "epoch-001",
            "type": type_,
            "updateId": "12345",
            "sequence": "67890",
            "exchangeTimestampMs": "1691636400000",
            "outerTimestampMs": "1691636400010",
            "receiveTimestampMs": "1691636400015",
            "bids": [{"priceTicks": "6499900", "qtySteps": "500"}],
            "asks": [{"priceTicks": "6500100", "qtySteps": "300"}],
        }

    def test_valid_snapshot(self):
        e = RawBookEvent(**self._make())
        assert e.type == "snapshot"
        assert e.depth == 50
        assert len(e.bids) == 1
        assert e.bids[0].price_ticks == 6499900

    def test_valid_depth_1000(self):
        e = RawBookEvent(**self._make(depth=1000))
        assert e.depth == 1000

    def test_invalid_depth(self):
        with pytest.raises(Exception):
            RawBookEvent(**self._make(depth=999))

    def test_zero_qty_allowed(self):
        """size=0 означает удалить уровень — допустимо."""
        payload = self._make(type_="delta")
        payload["bids"] = [{"priceTicks": "6499900", "qtySteps": "0"}]
        e = RawBookEvent(**payload)
        assert e.bids[0].qty_steps == 0

    def test_l50_and_l1000_independent(self):
        """L50 и L1000 — независимые экземпляры с разными connectionEpoch."""
        e50 = RawBookEvent(**self._make(depth=50))
        e1000 = RawBookEvent(**{**self._make(depth=1000),
                                "connectionEpoch": "epoch-002"})
        assert e50.connection_epoch != e1000.connection_epoch


# ===========================================================================
# contracts/schemas — RawRpiBookEvent
# ===========================================================================

class TestRawRpiBookEvent:
    def test_valid(self):
        payload = {
            "symbol": "BTCUSDT",
            "connectionEpoch": "epoch-rpi-001",
            "type": "snapshot",
            "updateId": "1",
            "sequence": "1",
            "exchangeTimestampMs": "1691636400000",
            "outerTimestampMs": "1691636400010",
            "receiveTimestampMs": "1691636400015",
            "bids": [
                {"priceTicks": "6499900",
                 "nonRpiQtySteps": "200",
                 "rpiQtySteps": "50"},
            ],
            "asks": [],
        }
        e = RawRpiBookEvent(**payload)
        assert e.depth == 50
        assert e.bids[0].rpi_qty_steps == 50
        assert e.bids[0].non_rpi_qty_steps == 200

    def test_rpi_separate_from_standard(self):
        """RPI event не является RawBookEvent — разные типы."""
        assert RawRpiBookEvent is not RawBookEvent


# ===========================================================================
# contracts/schemas — RawLiquidation
# ===========================================================================

class TestRawLiquidation:
    def _make(self, raw_side: str):
        if raw_side == "Buy":
            pos_side = "Long"
            forced = "Sell"
        else:
            pos_side = "Short"
            forced = "Buy"
        return {
            "symbol": "BTCUSDT",
            "rawSide": raw_side,
            "liquidatedPositionSide": pos_side,
            "inferredForcedFlow": forced,
            "bankruptcyPriceTicks": "6480000",
            "qtySteps": "200",
            "exchangeTimestampMs": "1691636400000",
            "outerTimestampMs": "1691636400500",
            "receiveTimestampMs": "1691636400505",
        }

    def test_buy_long_sell_normalization(self):
        """rawSide=Buy → Long → Sell (Roadmap §5.6)."""
        liq = RawLiquidation(**self._make("Buy"))
        assert liq.liquidated_position_side == LiquidatedPositionSide.LONG
        assert liq.inferred_forced_flow == TakerSide.SELL

    def test_sell_short_buy_normalization(self):
        """rawSide=Sell → Short → Buy (Roadmap §5.6)."""
        liq = RawLiquidation(**self._make("Sell"))
        assert liq.liquidated_position_side == LiquidatedPositionSide.SHORT
        assert liq.inferred_forced_flow == TakerSide.BUY

    def test_wrong_normalization_rejected(self):
        """Неправильная нормализация должна отвергаться."""
        bad = {
            **self._make("Buy"),
            "liquidatedPositionSide": "Short",  # неверно для Buy
            "inferredForcedFlow": "Buy",
        }
        with pytest.raises(Exception):
            RawLiquidation(**bad)

    def test_from_bybit_factory(self):
        """from_bybit автоматически выводит нормализацию."""
        liq = RawLiquidation.from_bybit(
            symbol="BTCUSDT",
            raw_side="Sell",
            bankruptcy_price_ticks="6450000",
            qty_steps="500",
            exchange_timestamp_ms="1691636400000",
            outer_timestamp_ms="1691636400500",
            receive_timestamp_ms="1691636400505",
        )
        assert liq.liquidated_position_side == LiquidatedPositionSide.SHORT
        assert liq.inferred_forced_flow == TakerSide.BUY

    def test_no_exchange_id(self):
        """У ликвидации нет exchange ID — дедупликация через reconnect невозможна."""
        liq = RawLiquidation(**self._make("Buy"))
        assert not hasattr(liq, "exchange_id")
        assert not hasattr(liq, "trade_id")


# ===========================================================================
# contracts/schemas — GapMarker
# ===========================================================================

class TestGapMarker:
    def test_trade_gap(self):
        gm = GapMarker(
            gapId="gap-001",
            symbol="BTCUSDT",
            feedKind=FeedKind.STANDARD,
            startTimeMs="1691636400000",
            detectedAtMs="1691636400100",
            previousConnectionEpoch="epoch-001",
            reason=GapReason.TRADE_OVERLAP_UNPROVEN,
        )
        assert gm.recoverability == GapRecoverability.OPEN
        assert gm.end_time_ms is None  # открытый gap

    def test_reconnect_gap(self):
        gm = GapMarker(
            gapId="gap-002",
            symbol="BTCUSDT",
            feedKind=FeedKind.STANDARD,
            startTimeMs="1691636400000",
            endTimeMs="1691636401000",
            detectedAtMs="1691636400100",
            previousConnectionEpoch="epoch-001",
            nextConnectionEpoch="epoch-002",
            reason=GapReason.DISCONNECT,
            recoverability=GapRecoverability.BOUNDED_UNRECOVERED,
        )
        assert gm.end_time_ms == 1691636401000
        assert gm.next_connection_epoch == "epoch-002"


# ===========================================================================
# contracts/schemas — RawEventEnvelope
# ===========================================================================

ENVELOPE_PAYLOAD = {
    "protocolVersion": "1.0",
    "schemaVersion": "1",
    "eventId": "BYBIT:linear:BTCUSDT:2290000000001234567",
    "eventType": "RAW_TRADE",
    "symbol": "BTCUSDT",
    "collectorId": "collector-01",
    "connectionEpoch": "epoch-001",
    "partitionId": "part-0",
    "eventTimeMs": "1691636400000",
    "outerTimeMs": "1691636400050",
    "receiveTimeMs": "1691636400055",
    "walOffset": "42",
    "dataRevision": "rev-001",
    "payload": {"tradeId": "2290000000001234567"},
}


class TestRawEventEnvelope:
    def test_all_required_fields_present(self):
        """Все обязательные поля §5.2 Roadmap присутствуют."""
        e = RawEventEnvelope(**ENVELOPE_PAYLOAD)
        # protocolVersion, schemaVersion, eventId, eventType
        assert e.protocol_version == "1.0"
        assert e.schema_version == 1
        assert e.event_id == "BYBIT:linear:BTCUSDT:2290000000001234567"
        assert e.event_type == EventType.RAW_TRADE
        # venue, category, symbol
        assert e.venue == "BYBIT"
        assert e.category == "linear"
        assert e.symbol == "BTCUSDT"
        # collectorId, connectionEpoch, partitionId
        assert e.collector_id == "collector-01"
        assert e.connection_epoch == "epoch-001"
        assert e.partition_id == "part-0"
        # timestamps
        assert e.event_time_ms == 1691636400000
        assert e.outer_time_ms == 1691636400050
        assert e.receive_time_ms == 1691636400055
        # walOffset, dataRevision
        assert e.wal_offset == 42
        assert e.data_revision == "rev-001"

    def test_optional_source_sequence_absent(self):
        e = RawEventEnvelope(**ENVELOPE_PAYLOAD)
        assert e.source_sequence is None
        assert e.update_id is None

    def test_source_sequence_present(self):
        payload = {**ENVELOPE_PAYLOAD, "sourceSequence": "9999"}
        e = RawEventEnvelope(**payload)
        assert e.source_sequence == 9999

    def test_event_id_deterministic(self):
        """eventId должен быть стабилен при replay — проверяем идентичность."""
        e1 = RawEventEnvelope(**ENVELOPE_PAYLOAD)
        e2 = RawEventEnvelope(**ENVELOPE_PAYLOAD)
        assert e1.event_id == e2.event_id

    def test_wal_offset_non_negative(self):
        bad = {**ENVELOPE_PAYLOAD, "walOffset": "-1"}
        with pytest.raises(Exception):
            RawEventEnvelope(**bad)

    def test_round_trip_json(self):
        """Envelope round-trip не теряет walOffset и eventId."""
        e = RawEventEnvelope(**ENVELOPE_PAYLOAD)
        raw = e.model_dump_json(by_alias=True)
        data = json.loads(raw)
        e2 = RawEventEnvelope(**data)
        assert e2.wal_offset == e.wal_offset
        assert e2.event_id == e.event_id
        assert e2.protocol_version == e.protocol_version


# ===========================================================================
# Backward compatibility
# ===========================================================================

class TestBackwardCompatibility:
    def test_extra_fields_ignored(self):
        """Новые optional поля не ломают парсинг старых клиентов."""
        payload = {**TRADE_PAYLOAD}
        # Удаляем поле которого не было в v0 — должно использоваться default
        del payload["isRpiTrade"]
        t = RawTrade(**payload)
        assert t.is_rpi_trade is False  # default

    def test_envelope_unknown_event_type_fails_explicitly(self):
        """Неизвестный eventType должен явно отклоняться, а не проглатываться."""
        bad = {**ENVELOPE_PAYLOAD, "eventType": "UNKNOWN_FUTURE_TYPE"}
        with pytest.raises(Exception):
            RawEventEnvelope(**bad)


# ===========================================================================
# Инвариант: нет float в persistent полях
# ===========================================================================

class TestNoFloatInPersistentSchemas:
    def test_raw_trade_price_no_float(self):
        bad = {**TRADE_PAYLOAD, "priceTicks": 65000.5}
        with pytest.raises(Exception):
            RawTrade(**bad)

    def test_raw_trade_qty_no_float(self):
        bad = {**TRADE_PAYLOAD, "qtySteps": 1.5}
        with pytest.raises(Exception):
            RawTrade(**bad)

    def test_book_level_price_no_float(self):
        with pytest.raises(Exception):
            RawBookLevel(priceTicks=65000.5, qtySteps=100)

    def test_book_checkpoint_coverage_bps_from_str(self):
        """coverageBps как Decimal принимается строкой."""
        bps = BookCheckpoint(
            symbol="BTCUSDT",
            depth=50,
            connectionEpoch="ep1",
            updateId="1",
            sequence=1,
            exchangeTimestampMs="1691636400000",
            outerTimestampMs="1691636400010",
            receiveTimestampMs="1691636400015",
            levelCount=50,
            coverageBoundaryTicks=100,
            coverageBps="199.50",
            isFeedRangeComplete=False,
        )
        assert bps.coverage_bps == Decimal("199.50")

    def test_book_checkpoint_coverage_bps_rejects_float(self):
        with pytest.raises(Exception):
            BookCheckpoint(
                symbol="BTCUSDT",
                depth=50,
                connectionEpoch="ep1",
                updateId="1",
                sequence=1,
                exchangeTimestampMs="1691636400000",
                outerTimestampMs="1691636400010",
                receiveTimestampMs="1691636400015",
                levelCount=50,
                coverageBoundaryTicks=100,
                coverageBps=199.5,   # float — запрещён
                isFeedRangeComplete=False,
            )
