"""
Формат WAL-фрейма: length + checksum/CRC.
Источник: Roadmap §6.2

    Frame имеет length + checksum/CRC; torn frame при старте отбрасывается
    до последнего валидного boundary и создаёт incident, если был объявлен
    durable.

Формат (little-endian, фиксированный header 16 байт):

    offset 0  : magic       uint32  = 0x42574C31 ("BWL1")
    offset 4  : version     uint16  = 1
    offset 6  : flags       uint16  (зарезервировано, 0)
    offset 8  : payload_len uint32
    offset 12 : crc32       uint32  (CRC32 полезной нагрузки)
    offset 16 : payload     payload_len байт

Причина фиксированного header: torn write определяется без разбора payload,
а checksum отделён от длины, поэтому повреждение длины не проходит валидацию.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

MAGIC = 0x42574C31
FRAME_VERSION = 1
HEADER_SIZE = 16
_HEADER_STRUCT = struct.Struct("<IHHII")

MAX_PAYLOAD_BYTES = 64 * 1024 * 1024  # защита от повреждённой длины


class FrameError(ValueError):
    """Базовая ошибка фрейма."""


class TornFrameError(FrameError):
    """Фрейм оборван: данных меньше, чем объявлено."""


class CorruptFrameError(FrameError):
    """Фрейм повреждён: не совпал magic/version/CRC."""


@dataclass(frozen=True)
class Frame:
    """Разобранный фрейм."""

    payload: bytes
    offset: int
    total_size: int

    @property
    def end_offset(self) -> int:
        return self.offset + self.total_size


def encode_frame(payload: bytes) -> bytes:
    """Собрать фрейм из полезной нагрузки."""
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise TypeError(f"payload должен быть bytes, получен {type(payload).__name__!r}")
    payload = bytes(payload)
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise FrameError(
            f"payload {len(payload)} байт превышает лимит {MAX_PAYLOAD_BYTES}"
        )
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    header = _HEADER_STRUCT.pack(MAGIC, FRAME_VERSION, 0, len(payload), crc)
    return header + payload


def frame_size(payload_len: int) -> int:
    return HEADER_SIZE + payload_len


def decode_frame(buffer: bytes, offset: int = 0) -> Frame:
    """Разобрать один фрейм начиная с offset.

    Бросает TornFrameError, если данных недостаточно (обрыв записи),
    и CorruptFrameError при несовпадении magic/version/CRC.
    """
    available = len(buffer) - offset
    if available <= 0:
        raise TornFrameError(f"нет данных на offset {offset}")
    if available < HEADER_SIZE:
        raise TornFrameError(
            f"неполный header на offset {offset}: {available} < {HEADER_SIZE}"
        )

    magic, version, flags, payload_len, crc = _HEADER_STRUCT.unpack_from(buffer, offset)

    if magic != MAGIC:
        raise CorruptFrameError(
            f"неверный magic на offset {offset}: 0x{magic:08X} != 0x{MAGIC:08X}"
        )
    if version != FRAME_VERSION:
        raise CorruptFrameError(
            f"неизвестная версия фрейма на offset {offset}: {version}"
        )
    if payload_len > MAX_PAYLOAD_BYTES:
        raise CorruptFrameError(
            f"payload_len {payload_len} на offset {offset} превышает лимит"
        )

    total = HEADER_SIZE + payload_len
    if available < total:
        raise TornFrameError(
            f"оборванный payload на offset {offset}: {available} < {total}"
        )

    payload = bytes(buffer[offset + HEADER_SIZE : offset + total])
    actual_crc = zlib.crc32(payload) & 0xFFFFFFFF
    if actual_crc != crc:
        raise CorruptFrameError(
            f"CRC не совпал на offset {offset}: 0x{actual_crc:08X} != 0x{crc:08X}"
        )

    return Frame(payload=payload, offset=offset, total_size=total)


@dataclass(frozen=True)
class ScanResult:
    """Итог сканирования буфера до последнего валидного boundary."""

    frames: tuple[Frame, ...]
    last_valid_offset: int
    trailing_bytes: int
    torn: bool
    corrupt: bool
    error: str | None = None


def scan_frames(buffer: bytes, start_offset: int = 0) -> ScanResult:
    """Прочитать все валидные фреймы, остановившись на первом плохом.

    Возвращает last_valid_offset — границу, до которой данные достоверны.
    Хвост после неё считается torn/corrupt и подлежит отбрасыванию.
    """
    frames: list[Frame] = []
    offset = start_offset
    torn = False
    corrupt = False
    error: str | None = None

    while offset < len(buffer):
        try:
            frame = decode_frame(buffer, offset)
        except TornFrameError as exc:
            torn = True
            error = str(exc)
            break
        except CorruptFrameError as exc:
            corrupt = True
            error = str(exc)
            break
        frames.append(frame)
        offset = frame.end_offset

    return ScanResult(
        frames=tuple(frames),
        last_valid_offset=offset,
        trailing_bytes=len(buffer) - offset,
        torn=torn,
        corrupt=corrupt,
        error=error,
    )
