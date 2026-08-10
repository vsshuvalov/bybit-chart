"""
WAL offsets и правила их продвижения.
Источник: Roadmap §6.2

Для каждой WAL partition хранятся:
    acceptedOffset   # запись полностью сформирована
    durableOffset    # CRC/frame и group commit fsync завершены
    closedOffset     # ACTIVE segment закрыт
    publishedOffset  # Parquet + manifest COMMITTED
    consumerOffset[logical-consumer-shard]

Инварианты:
    durable   <= accepted
    closed    <= durable
    published <= closed
Live publish не должен обгонять durableOffset: analytics и trading получают
только события с walOffset <= durableOffset (Roadmap §5.1, инвариант v1).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace


class OffsetInvariantError(ValueError):
    """Нарушение инварианта продвижения offsets."""


@dataclass(frozen=True)
class ConsumerOffset:
    """Checkpoint логического consumer.

    consumer_id стабилен по роли+shard и не зависит от PID/hostname
    (Roadmap §6.2). lease_generation растёт при takeover.
    """

    consumer_id: str
    wal_offset: int
    protocol_version: str
    lease_generation: int = 0

    def __post_init__(self) -> None:
        if self.wal_offset < 0:
            raise OffsetInvariantError(
                f"consumer {self.consumer_id}: wal_offset < 0: {self.wal_offset}"
            )
        if self.lease_generation < 0:
            raise OffsetInvariantError(
                f"consumer {self.consumer_id}: lease_generation < 0"
            )


@dataclass(frozen=True)
class OffsetSet:
    """Набор offsets одной WAL partition."""

    partition_id: str
    accepted: int = 0
    durable: int = 0
    closed: int = 0
    published: int = 0
    consumers: tuple[ConsumerOffset, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        self.validate()

    # ------------------------------------------------------------------
    # Инварианты
    # ------------------------------------------------------------------

    def validate(self) -> None:
        """Проверить инварианты. Бросает OffsetInvariantError."""
        for name, value in (
            ("accepted", self.accepted),
            ("durable", self.durable),
            ("closed", self.closed),
            ("published", self.published),
        ):
            if value < 0:
                raise OffsetInvariantError(f"{self.partition_id}: {name} < 0: {value}")

        if self.durable > self.accepted:
            raise OffsetInvariantError(
                f"{self.partition_id}: durable({self.durable}) > accepted({self.accepted}). "
                "fsync не может опережать запись."
            )
        if self.closed > self.durable:
            raise OffsetInvariantError(
                f"{self.partition_id}: closed({self.closed}) > durable({self.durable}). "
                "Нельзя закрыть сегмент за пределами durable."
            )
        if self.published > self.closed:
            raise OffsetInvariantError(
                f"{self.partition_id}: published({self.published}) > closed({self.closed}). "
                "Нельзя публиковать незакрытый диапазон."
            )

    # ------------------------------------------------------------------
    # Продвижение (только вперёд)
    # ------------------------------------------------------------------

    def advance_accepted(self, offset: int) -> "OffsetSet":
        if offset < self.accepted:
            raise OffsetInvariantError(
                f"{self.partition_id}: accepted не может убывать "
                f"({self.accepted} → {offset})"
            )
        return replace(self, accepted=offset)

    def advance_durable(self, offset: int) -> "OffsetSet":
        if offset < self.durable:
            raise OffsetInvariantError(
                f"{self.partition_id}: durable не может убывать "
                f"({self.durable} → {offset})"
            )
        return replace(self, durable=offset)

    def advance_closed(self, offset: int) -> "OffsetSet":
        if offset < self.closed:
            raise OffsetInvariantError(
                f"{self.partition_id}: closed не может убывать "
                f"({self.closed} → {offset})"
            )
        return replace(self, closed=offset)

    def advance_published(self, offset: int) -> "OffsetSet":
        if offset < self.published:
            raise OffsetInvariantError(
                f"{self.partition_id}: published не может убывать "
                f"({self.published} → {offset})"
            )
        return replace(self, published=offset)

    def upsert_consumer(self, consumer: ConsumerOffset) -> "OffsetSet":
        """Добавить/обновить checkpoint consumer.

        Откат назад разрешён только при новом lease_generation (takeover
        начинает с durable checkpoint, Roadmap §6.2).
        """
        existing = self.consumer(consumer.consumer_id)
        if existing is not None:
            if (
                consumer.wal_offset < existing.wal_offset
                and consumer.lease_generation <= existing.lease_generation
            ):
                raise OffsetInvariantError(
                    f"{self.partition_id}: consumer {consumer.consumer_id} "
                    f"откатывает offset ({existing.wal_offset} → {consumer.wal_offset}) "
                    "без новой lease generation"
                )
        others = tuple(c for c in self.consumers if c.consumer_id != consumer.consumer_id)
        return replace(self, consumers=others + (consumer,))

    def consumer(self, consumer_id: str) -> ConsumerOffset | None:
        for c in self.consumers:
            if c.consumer_id == consumer_id:
                return c
        return None

    # ------------------------------------------------------------------
    # Производные величины
    # ------------------------------------------------------------------

    def live_publish_ceiling(self) -> int:
        """Максимальный offset, который разрешено отдать analytics/trading.

        Roadmap §5.1: speculative pre-fsync tail запрещён.
        """
        return self.durable

    def min_consumer_offset(self, required_consumer_ids: frozenset[str]) -> int:
        """Минимальный offset среди обязательных consumers.

        Отсутствующий обязательный consumer считается стоящим на 0:
        его данные ещё нужны.
        """
        if not required_consumer_ids:
            return self.published
        result = None
        for consumer_id in required_consumer_ids:
            c = self.consumer(consumer_id)
            value = 0 if c is None else c.wal_offset
            result = value if result is None else min(result, value)
        return 0 if result is None else result

    def replay_safe_offset(
        self,
        parquet_capable_consumers: bool = True,
        wal_only_consumer_ids: frozenset[str] = frozenset(),
    ) -> int:
        """До какого offset WAL разрешено удалять.

        Roadmap §6.2: удаление только до replaySafeOffset — данные COMMITTED,
        checksum проверен, и каждый обязательный consumer либо прошёл offset,
        либо доказанно может прочитать тот же диапазон из committed Parquet.

        Отставший consumer, умеющий читать Parquet, не блокирует collector
        (он переключается на Parquet replay), поэтому базовая граница —
        published. Consumer из wal_only_consumer_ids читать Parquet не умеет
        и удерживает WAL до своего offset.
        """
        ceiling = self.published
        if wal_only_consumer_ids:
            ceiling = min(ceiling, self.min_consumer_offset(wal_only_consumer_ids))
        if not parquet_capable_consumers:
            ceiling = min(
                ceiling,
                self.min_consumer_offset(
                    frozenset(c.consumer_id for c in self.consumers)
                ),
            )
        return max(0, ceiling)

    def wal_retention_bytes(self) -> int:
        """Объём WAL, ещё не опубликованный в Parquet."""
        return max(0, self.accepted - self.published)
