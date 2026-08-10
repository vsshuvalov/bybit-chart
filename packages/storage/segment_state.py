"""
State machine файла сегмента и правила lease.
Источник: Roadmap §6.3

    ACTIVE
    → CLOSED_PENDING
    → PUBLISHING (lease)
    → COMMITTED
                  ↘ FAILED → retry/quarantine

Правила:
- Неизвестный orphan не усыновляется по короткому mtime ACTIVE-сегмента.
- corrupt, incomplete, legacy и schemaMismatch — разные состояния quarantine
  и не публикуются автоматически.
- Просроченный lease возвращает сегмент в CLOSED_PENDING.
- Удаление разрешено только для COMMITTED и только после retention checks.
- `.tmp`, ACTIVE и части незакрытой партиции удалять запрещено.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class SegmentState(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED_PENDING = "CLOSED_PENDING"
    PUBLISHING = "PUBLISHING"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"
    QUARANTINED = "QUARANTINED"


class QuarantineReason(str, Enum):
    """Разные причины quarantine — не сливаются в одну (Roadmap §6.3)."""

    CORRUPT = "corrupt"
    INCOMPLETE = "incomplete"
    LEGACY = "legacy"
    SCHEMA_MISMATCH = "schemaMismatch"


class SegmentTransitionError(RuntimeError):
    """Недопустимый переход state machine."""


class LeaseError(RuntimeError):
    """Ошибка владения lease."""


_ALLOWED: dict[SegmentState, frozenset[SegmentState]] = {
    SegmentState.ACTIVE: frozenset({SegmentState.CLOSED_PENDING}),
    SegmentState.CLOSED_PENDING: frozenset(
        {SegmentState.PUBLISHING, SegmentState.QUARANTINED}
    ),
    SegmentState.PUBLISHING: frozenset(
        {
            SegmentState.COMMITTED,
            SegmentState.FAILED,
            SegmentState.CLOSED_PENDING,  # lease expiry
        }
    ),
    SegmentState.FAILED: frozenset(
        {SegmentState.CLOSED_PENDING, SegmentState.QUARANTINED}
    ),
    SegmentState.COMMITTED: frozenset(),
    SegmentState.QUARANTINED: frozenset({SegmentState.CLOSED_PENDING}),
}


@dataclass(frozen=True)
class Lease:
    """Эксклюзивное право публикации сегмента.

    holder стабилен по роли+shard (не PID/hostname), generation растёт
    при каждом takeover — старый holder больше не может писать.
    """

    holder: str
    generation: int
    expires_at_ms: int

    def is_expired(self, now_ms: int) -> bool:
        return now_ms >= self.expires_at_ms


@dataclass(frozen=True)
class Segment:
    """Сегмент и его состояние."""

    segment_id: str
    partition_id: str
    state: SegmentState = SegmentState.ACTIVE
    start_offset: int = 0
    end_offset: int = 0
    lease: Lease | None = None
    quarantine_reason: QuarantineReason | None = None
    failure_reason: str | None = None
    retry_count: int = 0
    # Максимальная выданная generation. Сохраняется после снятия lease,
    # иначе просроченный holder смог бы перезахватить сегмент тем же
    # fencing token (Roadmap §19 Этап 2: старый token не пишет никогда).
    last_lease_generation: int = 0

    # ------------------------------------------------------------------
    # Переходы
    # ------------------------------------------------------------------

    def _check(self, target: SegmentState) -> None:
        allowed = _ALLOWED[self.state]
        if target not in allowed:
            raise SegmentTransitionError(
                f"{self.segment_id}: недопустимый переход {self.state.value} → {target.value}"
            )

    def close(self, end_offset: int) -> "Segment":
        """ACTIVE → CLOSED_PENDING."""
        self._check(SegmentState.CLOSED_PENDING)
        if end_offset < self.start_offset:
            raise SegmentTransitionError(
                f"{self.segment_id}: end_offset < start_offset"
            )
        return replace(self, state=SegmentState.CLOSED_PENDING, end_offset=end_offset)

    def claim(self, holder: str, generation: int, expires_at_ms: int) -> "Segment":
        """CLOSED_PENDING → PUBLISHING под lease.

        generation обязана строго превышать максимальную ранее выданную,
        даже если предыдущий lease уже снят по истечении срока. Иначе
        просроченный writer перезахватил бы сегмент старым fencing token.
        """
        self._check(SegmentState.PUBLISHING)
        floor = max(
            self.last_lease_generation,
            self.lease.generation if self.lease is not None else 0,
        )
        if generation <= floor:
            raise LeaseError(
                f"{self.segment_id}: generation {generation} не больше "
                f"ранее выданной {floor}"
            )
        return replace(
            self,
            state=SegmentState.PUBLISHING,
            lease=Lease(holder=holder, generation=generation, expires_at_ms=expires_at_ms),
            last_lease_generation=generation,
        )

    def commit(self, holder: str) -> "Segment":
        """PUBLISHING → COMMITTED. Только текущий holder."""
        self._check(SegmentState.COMMITTED)
        self._assert_holder(holder)
        return replace(self, state=SegmentState.COMMITTED, lease=None)

    def fail(self, holder: str, reason: str) -> "Segment":
        """PUBLISHING → FAILED."""
        self._check(SegmentState.FAILED)
        self._assert_holder(holder)
        return replace(
            self,
            state=SegmentState.FAILED,
            lease=None,
            failure_reason=reason,
            retry_count=self.retry_count + 1,
        )

    def expire_lease(self, now_ms: int) -> "Segment":
        """PUBLISHING → CLOSED_PENDING при истёкшем lease."""
        if self.state is not SegmentState.PUBLISHING:
            raise SegmentTransitionError(
                f"{self.segment_id}: expire_lease применим только к PUBLISHING"
            )
        if self.lease is None:
            raise LeaseError(f"{self.segment_id}: lease отсутствует")
        if not self.lease.is_expired(now_ms):
            raise LeaseError(
                f"{self.segment_id}: lease ещё активен до {self.lease.expires_at_ms}"
            )
        return replace(self, state=SegmentState.CLOSED_PENDING, lease=None)

    def retry(self) -> "Segment":
        """FAILED → CLOSED_PENDING."""
        self._check(SegmentState.CLOSED_PENDING)
        return replace(self, state=SegmentState.CLOSED_PENDING, failure_reason=None)

    def quarantine(self, reason: QuarantineReason) -> "Segment":
        """CLOSED_PENDING/FAILED → QUARANTINED с конкретной причиной."""
        self._check(SegmentState.QUARANTINED)
        return replace(
            self,
            state=SegmentState.QUARANTINED,
            quarantine_reason=reason,
            lease=None,
        )

    def _assert_holder(self, holder: str) -> None:
        if self.lease is None:
            raise LeaseError(f"{self.segment_id}: lease отсутствует")
        if self.lease.holder != holder:
            raise LeaseError(
                f"{self.segment_id}: holder {holder!r} не владеет lease "
                f"(владелец {self.lease.holder!r})"
            )

    # ------------------------------------------------------------------
    # Правила удаления
    # ------------------------------------------------------------------

    def may_delete(self, retention_ok: bool) -> bool:
        """Удаление только COMMITTED и только после retention checks."""
        return self.state is SegmentState.COMMITTED and retention_ok

    def is_adoptable_orphan(self) -> bool:
        """Orphan никогда не усыновляется автоматически (Roadmap §6.3)."""
        return False
