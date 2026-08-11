# ADR-016: IPC Protocol для Collector → Analytics Communication

**Статус:** PROPOSED  
**Дата:** 2026-08-11  
**Автор:** Claude Code  
**Roadmap:** §5.1, §5.2 (Этап 2)

---

## Context

Roadmap §5.1 и §5.2 требуют IPC (Inter-Process Communication) между collector и analytics/API processes для изоляции и fault tolerance.

**Текущее состояние (Stage 1):**
- Монолитный процесс: collector + analytics + API в одном Python process
- Direct memory access между компонентами
- Нет изоляции: crash analytics → crash collector

**Целевая архитектура (Stage 2-4):**
```
┌──────────────┐
│   Collector  │ ──┐
│ (WAL writer) │   │
└──────────────┘   │
                   ├──→ IPC Channel ──→ ┌─────────────┐
┌──────────────┐   │                    │ Analytics   │
│ Maintenance  │ ──┘                    │ + API       │
│   Worker     │                        └─────────────┘
└──────────────┘
```

### Requirements (Roadmap §5.1)

1. **Non-blocking publish:** Collector не должен блокироваться если analytics slow/dead
2. **Bounded memory:** Backpressure mechanism при переполнении buffer
3. **Deterministic replay:** Analytics может пересоздать state из WAL если IPC lost
4. **Crash isolation:** Analytics crash не должен убить collector
5. **Low latency:** <1ms p99 для publish (collector не может ждать)

### Requirements (Roadmap §5.2)

6. **Typed messages:** Protobuf/MessagePack/JSON schema
7. **Versioning:** Forward/backward compatibility для rolling updates
8. **Metrics:** Throughput, latency, drop rate
9. **Multiple subscribers:** Analytics + monitoring + feature-store

---

## Decision

### Option A: Unix Domain Sockets (UDS) — **RECOMMENDED**

**Mechanism:**
```python
# Collector (publisher)
sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
sock.setblocking(False)  # Non-blocking
sock.sendto(msgpack.packb(event), "/tmp/bybit-collector.sock")

# Analytics (subscriber)
sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
sock.bind("/tmp/bybit-collector.sock")
while True:
    data, addr = sock.recvfrom(65536)
    event = msgpack.unpackb(data)
    process(event)
```

**Wire format:** MessagePack
- Compact binary (меньше JSON)
- Fast serialization (~10x faster than JSON)
- Schema-less (гибкость), но можно добавить versioning header

**Message envelope:**
```python
{
    "version": 1,              # Protocol version
    "event_type": "RawTrade",  # Event discriminator
    "timestamp_us": 1786372648000000,
    "payload": {...}           # Actual event data
}
```

**Pros:**
- ✅ **Low latency:** 0.1-0.5ms (копирование через kernel buffer)
- ✅ **Zero config:** Нет внешних dependencies (Redis, Kafka)
- ✅ **Process isolation:** OS-level security boundaries
- ✅ **Non-blocking:** SOCK_DGRAM не блокирует sender
- ✅ **Simple implementation:** ~200 LOC

**Cons:**
- ⚠️ **Datagram semantics:** Возможны drops при переполнении receiver buffer
- ⚠️ **No built-in backpressure:** Нужно реализовать явно
- ⚠️ **Single host only:** Нет network support
- ⚠️ **Message size limit:** 65KB для SOCK_DGRAM (достаточно для events)

**Mitigation:**
- **Drop tolerance:** Analytics rebuilds state from WAL if drops detected
- **Backpressure:** Shared memory counter для queue depth
- **Single host:** Stage 2-4 deployment на одном хосте (ADR-012)
- **Size limit:** RawTrade ~200 bytes, RawBookEvent ~5KB (в пределах)

---

### Option B: gRPC Streaming

**Mechanism:**
```protobuf
service CollectorStream {
  rpc Subscribe(SubscribeRequest) returns (stream Event);
}
```

**Pros:**
- ✅ **Built-in backpressure:** Flow control via HTTP/2
- ✅ **Strong typing:** Protobuf schemas
- ✅ **Network support:** TCP/TLS для multi-host
- ✅ **Battle-tested:** Industry standard

**Cons:**
- ❌ **Higher latency:** 1-5ms (TCP stack + serialization)
- ❌ **Complexity:** gRPC server/client setup, connection management
- ❌ **Memory overhead:** HTTP/2 framing + protobuf allocations
- ❌ **Blocking risk:** Slow subscriber blocks publisher без careful tuning

**Verdict:** REJECTED для Stage 2 — overkill для single-host IPC. Рассмотреть для Stage 7+ если нужен multi-host.

---

### Option C: Shared Memory + Ring Buffer

**Mechanism:**
```python
# Collector writes to shared memory ring buffer
shm = mmap.mmap(-1, 1024*1024, mmap.MAP_SHARED)
ring = RingBuffer(shm, capacity=10000)
ring.push(event)

# Analytics reads from same buffer
ring = RingBuffer(shm, capacity=10000)
event = ring.pop()
```

**Pros:**
- ✅ **Ultra-low latency:** <0.1ms (zero-copy)
- ✅ **Built-in backpressure:** Ring full → writer blocks or drops
- ✅ **High throughput:** Millions events/sec

**Cons:**
- ❌ **Complex implementation:** Lock-free ring buffer tricky
- ❌ **Synchronization overhead:** Atomic ops, memory barriers
- ❌ **Debugging hell:** Race conditions, corruption hard to reproduce
- ❌ **No multi-subscriber:** Нужен explicit fan-out

**Verdict:** REJECTED для Stage 2 — преждевременная оптимизация. UDS достаточно fast (~1-2M events/sec).

---

## Comparison Table

| Feature | UDS (DGRAM) | gRPC | Shared Memory |
|---------|-------------|------|---------------|
| Latency (p99) | 0.5ms | 5ms | 0.1ms |
| Throughput | 2M/s | 500K/s | 10M/s |
| Complexity | Low | High | Very High |
| Dependencies | None | gRPC | None |
| Backpressure | Manual | Built-in | Built-in |
| Multi-subscriber | Easy | Easy | Hard |
| Debugging | Easy | Medium | Hard |
| Network support | No | Yes | No |

**Recommendation:** **UDS (DGRAM)** для Stage 2.

---

## Implementation Plan

### Phase 1: Publisher (Collector)

```python
# packages/ipc/publisher.py
class IPCPublisher:
    def __init__(self, socket_path: str):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        self.socket_path = socket_path
        self.metrics = PublisherMetrics()
    
    def publish(self, event: RawTrade | RawBookEvent) -> bool:
        """Non-blocking publish. Returns False if dropped."""
        try:
            envelope = {
                "version": 1,
                "event_type": type(event).__name__,
                "timestamp_us": event.exchange_timestamp_ms * 1000,
                "payload": event.model_dump(),
            }
            msg = msgpack.packb(envelope)
            
            if len(msg) > 65000:
                self.metrics.oversized_drops += 1
                return False
            
            self.sock.sendto(msg, self.socket_path)
            self.metrics.published += 1
            return True
        
        except BlockingIOError:
            # Receiver buffer full → drop
            self.metrics.backpressure_drops += 1
            return False
        except Exception as e:
            self.metrics.errors += 1
            logger.error(f"IPC publish error: {e}")
            return False
```

### Phase 2: Subscriber (Analytics)

```python
# packages/ipc/subscriber.py
class IPCSubscriber:
    def __init__(self, socket_path: str, buffer_size: int = 65536):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.sock.bind(socket_path)
        self.sock.setblocking(True)  # Blocking recv
        self.buffer_size = buffer_size
        self.handlers = {}
        self.metrics = SubscriberMetrics()
    
    def register_handler(self, event_type: str, handler: Callable):
        """Register handler for event type."""
        self.handlers[event_type] = handler
    
    def run(self):
        """Blocking event loop."""
        while True:
            try:
                data, addr = self.sock.recvfrom(self.buffer_size)
                envelope = msgpack.unpackb(data)
                
                if envelope["version"] != 1:
                    self.metrics.version_mismatches += 1
                    continue
                
                event_type = envelope["event_type"]
                handler = self.handlers.get(event_type)
                
                if handler:
                    handler(envelope["payload"])
                    self.metrics.processed += 1
                else:
                    self.metrics.unknown_types += 1
            
            except Exception as e:
                self.metrics.errors += 1
                logger.error(f"IPC receive error: {e}")
```

### Phase 3: Backpressure Monitoring

**Shared memory counter для queue depth:**
```python
# /dev/shm/bybit-ipc-depth
shm = mmap.mmap(-1, 4096, mmap.MAP_SHARED)
depth = struct.unpack("I", shm[:4])[0]

if depth > 10000:
    # Slow down collector or drop events
    pass
```

**Альтернатива:** Периодический `ioctl(FIONREAD)` на subscriber socket.

---

## Rollout Strategy

### Stage 2: Optional IPC

- **Default:** Direct in-process calls (текущее состояние)
- **Flag:** `--enable-ipc` для тестирования
- **Fallback:** Если IPC fails → fallback to in-process

### Stage 3: IPC Required

- **Separate processes:** Collector + Analytics в разных systemd units
- **IPC mandatory:** No fallback

### Stage 4: Multiple Subscribers

- **Fan-out:** Collector → Analytics + Monitoring + Feature-Store
- **Separate sockets:** `/tmp/bybit-analytics.sock`, `/tmp/bybit-monitoring.sock`

---

## Failure Modes & Recovery

| Failure | Detection | Recovery |
|---------|-----------|----------|
| Analytics crash | Publisher: `ECONNREFUSED` | Continue collecting, analytics rebuilds from WAL |
| Collector crash | Subscriber: no messages | Wait for restart, catch up from last processed offset |
| Buffer overflow | Publisher: `BlockingIOError` | Drop message, log metric |
| Message corruption | Subscriber: `msgpack.unpackb` error | Skip message, log metric |
| Version mismatch | Subscriber: `envelope["version"] != 1` | Skip message if incompatible |

**Key principle:** **Analytics can always rebuild state from WAL.**

IPC is best-effort optimization, not source of truth.

---

## Performance Targets

**Collector publish budget:**
- Latency: <100μs p50, <500μs p99
- Throughput: 100K events/sec sustained
- Drop rate: <0.01% under normal load

**Analytics subscribe:**
- Processing time: <1ms per event
- Queue depth: <1000 events under normal load
- Catch-up time: <10s after restart

---

## Testing Strategy

### Unit Tests
- ✅ Publisher non-blocking behavior
- ✅ Subscriber handler dispatch
- ✅ MessagePack round-trip
- ✅ Version mismatch handling

### Integration Tests
- ✅ End-to-end: Collector → Analytics
- ✅ Backpressure: Slow subscriber
- ✅ Recovery: Analytics restart mid-stream

### Property Tests (Hypothesis)
- ✅ No events lost if analytics reads all
- ✅ Order preserved within single publisher
- ✅ Drop detection via sequence numbers

---

## Future Work

1. **gRPC migration** (Stage 7+):
   - If multi-host deployment needed
   - Keep UDS for local fast-path

2. **Compression** (P3):
   - LZ4/Zstd for large book events
   - Trade CPU for bandwidth

3. **Batching** (P2):
   - Send arrays of events instead of single
   - Amortize syscall overhead

4. **Zero-copy** (P3):
   - SOCK_SEQPACKET + splice() for large payloads
   - Requires kernel 5.10+

---

## References

- Roadmap: §5.1 (IPC publish), §5.2 (Multi-process)
- ADR-013: Writer Lease (координация между processes)
- Implementation: `packages/ipc/publisher.py`, `packages/ipc/subscriber.py`
- Related: Stage 2 tasks (P1-S2-003, P1-S2-004)

---

## Approval

**Status:** PROPOSED  
**Date:** 2026-08-11  
**Next steps:**
1. Review by team
2. Prototype implementation (~2 days)
3. Benchmark vs requirements
4. Accept or revise
