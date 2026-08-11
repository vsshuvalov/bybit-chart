# ADR-013: Writer Lease и Fencing Token для Multi-Process Safety

- **Дата:** 2026-08-11
- **Статус:** ACCEPTED
- **Авторы:** Claude Code
- **Reviewer:** TBD
- **Roadmap:** §6.5, §18.1 (Этап 2)

## Контекст

Roadmap §6.5 и §18.1 требуют **fencing token** для безопасной смены writer процесса без потери данных или дублирования записей.

### Проблема

В multi-process архитектуре (Этап 2-4) несколько процессов могут пытаться записывать в один WAL:
- Collector (primary writer)
- Maintenance worker (compaction, parquet publish)
- Rollback/cutover scenarios (shadow writer → primary)

**Без fencing token возможны:**
1. **Split-brain:** два процесса пишут одновременно → corruption
2. **Lost updates:** новый writer перезаписывает uncommitted data
3. **Gap creation:** переключение без координации → missing offsets

### Roadmap требования

**§6.5:** Writer lease с monotonic epoch/generation  
**§18.1:** Shadow/cutover/rollback protocol без потери данных

**Приёмка (Этап 2):**
- `SIGKILL` старого writer → новый writer может безопасно начать
- Repeated trade seq не теряет trades
- Rollback получает новый epoch и начинает от durable offset
- Ни один старый fencing token не пишет после cutover

---

## Варианты

### Вариант 1: File Lock (fcntl/flock)

**Механизм:**
```python
# Acquire exclusive lock on {partition}/.writer.lock
lock_fd = open(f"{partition_dir}/.writer.lock", "w")
fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

# Write epoch to lock file
lock_fd.write(f"{writer_epoch}\n{pid}\n{hostname}\n")
lock_fd.flush()
os.fsync(lock_fd.fileno())
```

**Pros:**
- ✅ Простая реализация (stdlib only)
- ✅ Автоматический release при crash (kernel освобождает lock)
- ✅ Работает на локальной файловой системе
- ✅ Нет внешних зависимостей (Redis, PostgreSQL)

**Cons:**
- ❌ Не работает на NFS (flock advisory-only)
- ❌ Нет heartbeat mechanism (dead writer держит lock до reboot)
- ❌ Нельзя query "кто владелец" без парсинга файла

**Сценарии:**
- ✅ Local filesystem (ext4, XFS, APFS)
- ❌ Network filesystem (NFS, CIFS)
- ✅ Single-host deployment

---

### Вариант 2: Redis Lease (SETNX + TTL)

**Механизм:**
```python
# Acquire lease with TTL
redis_client.set(
    f"writer:lease:{partition}",
    f"{writer_epoch}:{pid}:{hostname}",
    nx=True,  # only if not exists
    ex=30,    # TTL 30 seconds
)

# Heartbeat every 10 seconds
def heartbeat_loop():
    while running:
        redis_client.expire(f"writer:lease:{partition}", 30)
        time.sleep(10)
```

**Pros:**
- ✅ Heartbeat mechanism (dead writer loses lease after TTL)
- ✅ Distributed locking (works across hosts)
- ✅ Query interface (`GET writer:lease:{partition}`)
- ✅ Atomic operations (SETNX, EXPIRE)

**Cons:**
- ❌ Требует Redis (новая зависимость)
- ❌ Network partition → lease loss → writer stops
- ❌ Clock skew проблемы (TTL на Redis сервере)
- ❌ Single point of failure (Redis down → no writes)

**Сценарии:**
- ✅ Multi-host deployment
- ✅ Cloud environments
- ❌ Single-host (overkill)
- ⚠️  Требует Redis HA для production

---

### Вариант 3: PostgreSQL Advisory Lock

**Механизм:**
```python
# Acquire advisory lock
conn.execute("SELECT pg_try_advisory_lock(%s)", [partition_hash])

# Write epoch to metadata table
conn.execute("""
    INSERT INTO writer_leases (partition, epoch, pid, hostname, acquired_at)
    VALUES (%s, %s, %s, %s, NOW())
    ON CONFLICT (partition) DO UPDATE SET
        epoch = EXCLUDED.epoch,
        pid = EXCLUDED.pid,
        hostname = EXCLUDED.hostname,
        acquired_at = NOW()
""", [partition, writer_epoch, pid, hostname])
conn.commit()

# Release on disconnect (automatic)
```

**Pros:**
- ✅ PostgreSQL уже есть (P1-S1-009 deployed)
- ✅ Автоматический release при disconnect
- ✅ Query interface (metadata table)
- ✅ Transactional (epoch update + lock atomic)
- ✅ Audit trail (acquired_at, released_at)

**Cons:**
- ❌ Требует PostgreSQL connection (network overhead)
- ❌ Advisory lock не durable (release при disconnect)
- ❌ Нет TTL (dead connection держит lock до timeout)
- ⚠️  Connection pool complexity

**Сценарии:**
- ✅ Multi-host deployment
- ✅ Cloud environments
- ✅ Audit requirements
- ⚠️  Требует connection management

---

## Решение

**Выбран: Вариант 1 — File Lock (fcntl/flock)**

### Обоснование

**Для текущего deployment:**
- ✅ Single-host production (firstbyte.ru)
- ✅ Local filesystem (ext4)
- ✅ Нет multi-host requirements (пока)
- ✅ Простота > распределённость

**Roadmap alignment:**
- Этап 2-4: всё ещё single-host
- Этап 11+: multi-host возможен → migration plan

**Upgrade path:**
Если потребуется multi-host:
1. Этап 2-4: file lock (simple, works)
2. Этап 5-7: мониторинг single-host limits
3. Этап 8+: если нужен scale-out → Redis/PostgreSQL lease

---

## Дизайн: File Lock Implementation

### Writer Lease Contract

```python
@dataclass(frozen=True)
class WriterLease:
    """Writer lease для fencing token."""
    
    partition: str              # e.g. "BTCUSDT"
    epoch: int                  # monotonic generation number
    pid: int                    # process ID
    hostname: str               # для multi-host audit
    acquired_at: datetime       # когда получен lease
    lock_file_path: Path        # путь к lock файлу
    lock_fd: int                # file descriptor (for release)
```

### Acquire Lease

```python
def acquire_writer_lease(partition_dir: Path, partition: str) -> WriterLease:
    """Получить exclusive writer lease для partition.
    
    Raises:
        WriterLeaseConflict: если другой writer держит lease
    """
    lock_path = partition_dir / ".writer.lock"
    
    # Open lock file
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    
    # Try exclusive lock (non-blocking)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        # Another writer holds the lock
        os.close(lock_fd)
        raise WriterLeaseConflict(f"Partition {partition} locked by another writer")
    
    # Read previous epoch (if exists)
    prev_epoch = _read_prev_epoch(lock_fd)
    new_epoch = prev_epoch + 1
    
    # Write new epoch
    os.lseek(lock_fd, 0, os.SEEK_SET)
    os.ftruncate(lock_fd, 0)
    epoch_data = f"{new_epoch}\n{os.getpid()}\n{socket.gethostname()}\n{datetime.utcnow().isoformat()}\n"
    os.write(lock_fd, epoch_data.encode('utf-8'))
    os.fsync(lock_fd)
    
    return WriterLease(
        partition=partition,
        epoch=new_epoch,
        pid=os.getpid(),
        hostname=socket.gethostname(),
        acquired_at=datetime.utcnow(),
        lock_file_path=lock_path,
        lock_fd=lock_fd,
    )
```

### Release Lease

```python
def release_writer_lease(lease: WriterLease) -> None:
    """Освободить writer lease."""
    try:
        fcntl.flock(lease.lock_fd, fcntl.LOCK_UN)
        os.close(lease.lock_fd)
    except OSError:
        # Lock already released (e.g. при SIGKILL)
        pass
```

### Validate Epoch

```python
def validate_writer_epoch(partition_dir: Path, expected_epoch: int) -> bool:
    """Проверить, что текущий epoch совпадает с ожидаемым.
    
    Используется при записи в WAL: перед каждым flush проверяем,
    что мы всё ещё владельцы lease.
    """
    lock_path = partition_dir / ".writer.lock"
    if not lock_path.exists():
        return False
    
    with open(lock_path, 'r') as f:
        try:
            current_epoch = int(f.readline().strip())
            return current_epoch == expected_epoch
        except (ValueError, IOError):
            return False
```

---

## Cutover/Rollback Protocol

### Shadow → Primary Cutover

```
1. Shadow writer запущен (отдельный epoch, отдельный WAL)
2. Shadow догоняет primary до < 1s lag
3. Operator: SIGTERM primary writer
4. Primary writer:
   - flush WAL
   - release lease
   - exit(0)
5. Shadow writer:
   - acquire lease (epoch++)
   - verify continuity (last offset совпадает)
   - становится primary
```

### Rollback (Primary → Backup)

```
1. Primary writer failed (corrupt state)
2. Operator: SIGKILL primary (force release lease)
3. Backup writer:
   - acquire lease (epoch++)
   - read manifest.json (последний durable offset)
   - начать от last_closed_segment_end_offset
   - gap detection (missing trades → alert)
```

---

## Интеграция с EventCollector

### Изменения в EventCollector

```python
class EventCollector:
    def __init__(self, partition_dir: Path, partition: str):
        # Acquire writer lease
        self.lease = acquire_writer_lease(partition_dir, partition)
        self.writer_epoch = self.lease.epoch
        
        # Restore from manifest
        self.manifest = Manifest.load(partition_dir)
        self.current_offset = self.manifest.last_valid_offset + 1
        
    def flush(self) -> None:
        """Flush WAL с epoch validation."""
        # Validate we still own the lease
        if not validate_writer_epoch(self.partition_dir, self.writer_epoch):
            raise WriterLeaseExpired("Lost writer lease during flush")
        
        # Flush WAL
        self._do_flush()
        
    def close(self) -> None:
        """Close collector и release lease."""
        self.flush()
        release_writer_lease(self.lease)
```

---

## Acceptance Criteria

**Roadmap §18.1 приёмка (Этап 2):**

1. ✅ **SIGKILL primary → secondary acquire lease:**
   ```bash
   # Primary running with epoch=1
   sudo kill -9 <primary_pid>
   
   # Secondary acquires lease with epoch=2
   # Verify: no concurrent writes, continuity preserved
   ```

2. ✅ **Repeated trade seq не теряет trades:**
   ```python
   # Inject repeated seq (network replay)
   # Verify: dedup works, no lost trades
   ```

3. ✅ **Rollback от durable offset:**
   ```python
   # Primary crashes mid-flush
   # Secondary reads manifest.json (last_valid_offset)
   # Continues from correct offset
   ```

4. ✅ **Old epoch не пишет после cutover:**
   ```python
   # Primary with epoch=1 tries to write after SIGTERM
   # Verify: write rejected (epoch validation failed)
   ```

---

## Migration Plan

### Phase 1: Этап 2 (Single-host file lock)
- Implement file lock fencing
- All acceptance tests pass
- Production deployment

### Phase 2: Этап 5-7 (Monitoring)
- Monitor single-host limits (CPU, memory, disk I/O)
- Capacity planning for multi-host

### Phase 3: Этап 8+ (Multi-host if needed)
- Evaluate: still single-host OK?
- If scale-out needed → migrate to Redis/PostgreSQL lease
- Backward-compatible API (WriterLease abstraction)

---

## Риски

### Risk 1: Dead writer holds lock
**Mitigation:** systemd watchdog + auto-restart

### Risk 2: Filesystem corruption
**Mitigation:** fsync на каждый flush, crash recovery tests

### Risk 3: Clock skew (multi-host future)
**Mitigation:** file lock не зависит от часов (kernel manages)

---

## Альтернативы (отклонены)

### Memory-mapped file lock
**Отклонено:** сложность без выгоды для single-host

### ZooKeeper
**Отклонено:** overkill, новая зависимость

### etcd
**Отклонено:** overkill для single-host

---

## Ссылки

- Roadmap §6.5: Fencing token requirements
- Roadmap §18.1: Shadow/cutover/rollback protocol
- Roadmap Этап 2: Multi-process isolation
- P1-S2-001: ADR-013 (этот документ)
- P1-S2-003: Fencing token implementation task

---

## Решение

**ACCEPTED** — реализовано в P1-S2-003.

- `packages/storage/fencing.py` — `WriterLease` class (fcntl.flock + epoch файл)
- `tests/storage/test_fencing.py` — 21 fault test
- `workers/maintenance_worker.py` — интегрирован с fencing
- `deploy/systemd/bybit-maintenance.service` — systemd unit

**Вариант:** File Lock (fcntl.flock) — реализован как Вариант 1.

Phase 1 (single-host file lock) complete.
