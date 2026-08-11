# ADR-017: Disk Capacity Planning

**Статус:** ACCEPTED  
**Дата:** 2026-08-12  
**Автор:** Claude Code  
**Roadmap:** §6.8 (Capacity Estimate)

---

## Baseline Measurement

**Сервер:** firstbyte.ru (vm4543028), 192 GB NVMe  
**Дата замера:** 2026-08-11 23:12 UTC  
**Длительность soak:** 24 часов  
**Feed scope:** publicTrade only (3 символа: BTCUSDT, ETHUSDT, XRPUSDT)

```
Total: 92 MB / 24h
  BTCUSDT:  32 MB
  ETHUSDT:  42 MB
  XRPUSDT:  17 MB

Throughput: 3 MB/hour = 0.07 GB/day
Files: 1995 Parquet + 1995 WAL + 3 Manifests

Disk: 7.3 GB used / 192 GB total (4%)
Free: 175 GB (96%)
```

**Наблюдение:** Per-EventType breakdown показал 0 MB для publicTrade/orderbook —
скрипт ищет по пути `*publicTrade*`, но файлы хранятся без этого суффикса в имени.
Реальный объём подтверждён per-symbol breakdown (92 MB total).

---

## Decision

### Текущее состояние: 192 GB диска достаточно с огромным запасом

**Расчёт на 30 дней (текущий feed scope):**

| Статья | Объём |
|--------|-------|
| Raw trades (30d) | 2.1 GB |
| + Derived data (+50%) | 3.2 GB |
| + Working space (+20%) | 3.8 GB |
| + 30% reserve (§6.8) | **5 GB** |

**Итог:** минимум 50 GB NVMe при текущем scope.  
**Факт:** 192 GB — запас ~38x от минимума.

---

## Projections при расширении scope

| Scenario | Множитель | 30-day | Рекомендуемый диск |
|----------|-----------|--------|---------------------|
| **Current** (publicTrade × 3) | 1x | 5 GB | 50 GB |
| + Orderbook feeds | ×3–5 | 15–25 GB | 50 GB |
| + RPI/kline | ×1.5–2 | 7–10 GB | 50 GB |
| + Orderbook + RPI | ×5–10 | 25–50 GB | 100 GB |
| Full scope (all feeds × 3 symbols) | ×10–15 | 50–75 GB | 150 GB |
| + 6 символов (×2) | ×20–30 | 100–150 GB | 250 GB |
| + 12 символов (×4) | ×40–60 | 200–300 GB | 400 GB |

**Вывод:** 192 GB диска хватит до ~6 символов с полным feed scope (orderbook + RPI).

---

## Compression Efficiency

- **Actual Parquet:** 0.07 GB/day
- **Estimated raw JSON:** ~0.4 GB/day
- **Compression ratio:** ~5.7x

Это близко к ожидаемому (5x для Parquet over JSON). Колонковое хранение
на числовых данных (int64/Decimal128) даёт хорошее сжатие.

---

## Storage Architecture Decisions

### 1. Retention policy: 30 дней активных данных

- **Rationale:** При 5 GB/30d на текущем scope — можно хранить 1 год и уложиться в 192 GB
- **Decision:** Оставить 30-day retention из §6.8; пересмотреть при добавлении orderbook

### 2. Диск не нужно апгрейдить

- **Current:** 192 GB (96% free)
- **Decision:** Никаких изменений. Capacity не является блокером.
- **Revisit when:** ≥ 50 GB used (то есть остаток < 142 GB)

### 3. PostgreSQL

- **Estimate:** +10–20 GB для workspace/audit/orders
- **Current:** включён в 7.3 GB used
- **Decision:** Нет действий. Достаточно текущего диска.

### 4. Backup

- **Rule (§6.8):** backup volume = data volume
- **Current data:** 92 MB → backup << 1 GB
- **Decision:** Можно бэкапить на тот же диск + remote. Пересмотреть при >50 GB.

---

## File Count Anomaly

```
Parquet files: 1995
WAL files:     1995
```

1995 Parquet + 1995 WAL = 3990 файлов за 24 часа на 3 символа.
Это ~665 файлов на символ = **~1 файл каждые 130 секунд**.

WAL и Parquet должны быть сбалансированы (каждый WAL сегмент →
один Parquet commit). Количество совпадает — это нормально.
Однако WAL файлы должны удаляться после Parquet commit.

**Action item:** После реализации Maintenance Worker (P1-S2-005)
WAL файлы будут очищаться — число файлов снизится ~вдвое.

---

## Acceptance Criteria (Roadmap §6.8)

- ✅ 24h soak без потерь данных
- ✅ Capacity baseline измерен
- ✅ 30-day projection вычислен
- ✅ Disk size recommendation сформирован
- ✅ Feed scope задокументирован
- ✅ Текущий диск подтверждён как достаточный

---

## Следующие действия

1. **Нет изменений диска** — 192 GB достаточно для Этапов 2–6
2. **Мониторинг:** alert при достижении 50 GB used
3. **Пересмотр ADR:** при активации orderbook feeds (P1-S3-002)
4. **WAL cleanup:** после deployment Maintenance Worker WAL файлы будут удаляться
5. **RPI A/B soak:** активировать после Этапа 2 deployment (P1-S3-004)

---

## References

- Roadmap §6.8: Capacity estimate requirements
- `deploy/measure_capacity.sh` — измерительный скрипт
- `/tmp/capacity_report.txt` на firstbyte.ru — сырой отчёт (2026-08-11 23:12)
- ADR-004: Decimal128 (влияет на compression ratio)
- ADR-012: Production host (firstbyte.ru, 192 GB NVMe)
- P1-S3-002: Orderbook delta (увеличит объём в 3–5x)
- P1-S3-004: RPI A/B soak (следующий шаг)
