# Contributing to Bybit Chart Platform

Спасибо за интерес к проекту! Этот документ описывает процесс внесения изменений.

---

## Быстрый старт

```bash
# Clone repository
git clone https://github.com/vsshuvalov/bybit-chart.git
cd bybit-chart

# Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r deploy/dependencies/darwin-arm64/requirements.lock  # macOS
# или
pip install -r deploy/dependencies/linux-x86_64/requirements.lock  # Linux

# Run tests
pytest tests/ -v
```

---

## Code Style

Проект использует [Ruff](https://docs.astral.sh/ruff/) для linting и formatting.

**Перед коммитом:**
```bash
# Format code
ruff format .

# Check linting
ruff check .

# Run tests
pytest tests/ -q
```

**Настройки:** `pyproject.toml` → `[tool.ruff]`

---

## Testing Requirements

### Обязательно для всех PR:

✅ **Unit tests** — покрытие новой функциональности
- Файлы: `tests/contracts/`, `tests/analytics/`, `tests/integration/`
- Запуск: `pytest tests/`

✅ **Property tests** (для детерминизма) — при добавлении aggregators/detectors
- Используйте Hypothesis
- Примеры: `tests/analytics/test_*_properties.py`

✅ **Integration tests** — для новых API endpoints
- Примеры: `tests/integration/test_*_api.py`

### Test markers:
```python
pytestmark = pytest.mark.analytics  # Для analytics модулей
pytestmark = pytest.mark.contract   # Для contracts/schemas
pytestmark = pytest.mark.property   # Для property-based tests
pytestmark = pytest.mark.integration # Для integration tests
```

### Минимальные требования:
- ✅ Все существующие tests проходят
- ✅ Новый код покрыт тестами (>80% coverage)
- ✅ Property tests для алгоритмов агрегации

---

## Architecture Decision Records (ADR)

Для **значимых архитектурных решений** создаём ADR:

**Когда нужен ADR:**
- Выбор между несколькими подходами (UDS vs gRPC)
- Изменение wire format / storage format
- Новый процесс в multi-process architecture
- Изменение API contract

**Как создать:**
```bash
# Создать новый ADR
cp docs/adr/ADR-000-template.md docs/adr/ADR-017-your-decision.md
```

**Структура ADR:**
1. Context — проблема и требования
2. Decision — выбранное решение
3. Alternatives Considered — отвергнутые варианты
4. Consequences — последствия (positive/negative)
5. References — связанные документы

**Примеры:** `docs/adr/ADR-014-heatmap-tile-design.md`

---

## Commit Guidelines

### Формат commit message:
```
<type>: <short summary>

<body>
- Bullet points для деталей
- Roadmap references (§X.Y)
- Related issues (#123)

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

### Types:
- `feat:` — новая функциональность
- `fix:` — исправление бага
- `docs:` — изменения в документации
- `test:` — добавление/изменение тестов
- `refactor:` — рефакторинг без изменения функциональности
- `perf:` — performance improvements
- `chore:` — обновление dependencies, build config

### Примеры:
```
feat: Heatmap tiles implementation (Roadmap §9.2 Этап 6)

- HeatmapTile schema + QueryParams
- Tile aggregator с price/time binning
- GET /api/v1/analytics/heatmap endpoint
- 11 unit tests + 6 property tests

Roadmap §9.2 требования:
✅ Tile cache для efficient queries
✅ Configurable bin/interval parameters

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

---

## Pull Request Process

### 1. Create Feature Branch
```bash
git checkout -b feature/your-feature-name
# или
git checkout -b fix/your-bug-fix
```

### 2. Make Changes
- Следуйте code style (ruff)
- Добавьте tests
- Обновите документацию
- Создайте ADR если нужно

### 3. Verify
```bash
# Format
ruff format .

# Lint
ruff check .

# Tests
pytest tests/ -v

# Type check (optional)
mypy packages/analytics/
```

### 4. Commit
```bash
git add .
git commit -m "feat: your feature description"
```

### 5. Push & Create PR
```bash
git push origin feature/your-feature-name
```

**GitHub:** создайте Pull Request с описанием:
- Что изменено
- Зачем (Roadmap reference или issue)
- Как протестировано
- Breaking changes (если есть)

### 6. Review & Merge
- ✅ CI должен быть green
- ✅ Code review от maintainer
- ✅ Все комментарии resolved
- ✅ Squash & merge в main

---

## Adding New Analytics Module

**Template для нового детектора:**

### 1. Contract (schema)
```python
# contracts/your_feature.py
from pydantic import BaseModel

class YourFeatureEvent(BaseModel):
    """Event schema for your feature."""
    timestamp_ms: int
    value: float
    confidence: float
    metadata: dict
```

### 2. Implementation
```python
# packages/analytics/your_feature.py
class YourFeatureDetector:
    """Detector for your feature (Roadmap §X.Y)."""
    
    def __init__(self, window_ms: int = 60000):
        self.window_ms = window_ms
        self._state = {}
    
    def process(self, event) -> YourFeatureEvent | None:
        """Process event — return result if ready."""
        pass
    
    def flush(self) -> list[YourFeatureEvent]:
        """Flush pending state (для chunk boundaries)."""
        pass
```

### 3. Tests
```python
# tests/analytics/test_your_feature.py
import pytest
from packages.analytics.your_feature import YourFeatureDetector

pytestmark = pytest.mark.analytics

class TestYourFeatureDetector:
    def test_basic_detection(self):
        detector = YourFeatureDetector()
        # ...
```

### 4. Property Tests (Hypothesis)
```python
# tests/analytics/test_your_feature_properties.py
from hypothesis import given, strategies as st

pytestmark = [pytest.mark.analytics, pytest.mark.property]

@given(inputs=st.lists(st.integers()))
def test_deterministic(inputs):
    # Проверить determinism
    pass
```

### 5. API Endpoint
```python
# packages/api/app.py
@app.get("/api/v1/analytics/your-feature")
async def get_your_feature(...):
    """Your feature API (Roadmap §X.Y)."""
    pass
```

### 6. Documentation
- Обновить `packages/analytics/README.md`
- Создать ADR если архитектурное решение
- Обновить `ROADMAP_STATUS.md`

---

## Project Structure

```
bybit-chart/
├── contracts/           # Pydantic schemas (wire format)
├── packages/
│   ├── analytics/      # Analytics modules (detectors, aggregators)
│   ├── api/            # FastAPI application
│   ├── storage/        # WAL, Parquet, Manifest
│   ├── bybit/          # Bybit WebSocket client
│   └── monitoring/     # Metrics, logging
├── tests/
│   ├── contracts/      # Contract tests
│   ├── analytics/      # Analytics unit + property tests
│   ├── integration/    # API integration tests
│   └── fault/          # Fault injection tests
├── docs/
│   ├── adr/            # Architecture Decision Records
│   └── architecture/   # System design docs
└── deploy/             # Deployment configs, scripts
```

---

## Common Patterns

### Analytics Module Pattern
```python
class Detector:
    def __init__(self, ...):
        self._state = {}  # Stateful для streaming
    
    def process(self, event) -> Result | None:
        # Process одно событие
        # Return result если готов
        pass
    
    def flush(self) -> list[Result]:
        # Вернуть pending results
        # Важно для chunk boundaries
        pass
```

### API Endpoint Pattern
```python
@app.get("/api/v1/analytics/feature")
async def get_feature(
    symbol: str = Query(...),
    start_ms: int = Query(..., ge=0),
    end_ms: int = Query(..., ge=0),
):
    """Feature API (Roadmap §X.Y)."""
    try:
        # Read from Parquet
        events = reader.read_range(...)
        
        # Compute analytics
        result = compute_feature(events)
        
        return JSONResponse(content={...})
    except FileNotFoundError:
        raise HTTPException(404, "Symbol not found")
    except Exception as e:
        raise HTTPException(500, f"Error: {e}")
```

---

## Performance Guidelines

### Analytics Modules
- ✅ O(1) memory для streaming detectors
- ✅ Window-based state management (drop old events)
- ✅ Deterministic (same inputs → same outputs)
- ✅ Chunk-boundary independent

### API Endpoints
- ✅ Pagination для больших результатов
- ✅ Query validation (start < end)
- ✅ Error handling (404, 500)
- ✅ Response time <1s для typical queries

---

## Security

### Secrets Management
- ❌ НЕ коммитить API keys, passwords, tokens
- ❌ НЕ коммитить production data
- ✅ Используйте environment variables
- ✅ `.gitignore` для sensitive files

### Code Review Checklist
- ✅ No hardcoded credentials
- ✅ Input validation для API endpoints
- ✅ SQL injection prevention (parameterized queries)
- ✅ No arbitrary code execution

---

## Getting Help

**Questions:**
- GitHub Issues — для bug reports и feature requests
- GitHub Discussions — для вопросов и идей

**Documentation:**
- `ROADMAP_STATUS.md` — текущий прогресс
- `NEXT.md` — next priorities
- `docs/adr/` — architectural decisions
- `packages/analytics/README.md` — analytics modules guide

**Contact:**
- GitHub: @vsshuvalov

---

## License

See `LICENSE` file for details.

---

**Спасибо за вклад в проект!** 🚀
