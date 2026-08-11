# Pull Request

## Description

<!-- Краткое описание изменений -->

## Type of Change

<!-- Отметьте relevant опции -->

- [ ] Bug fix (не breaking change, исправляет issue)
- [ ] New feature (не breaking change, добавляет функциональность)
- [ ] Breaking change (fix или feature, ломающий существующий функционал)
- [ ] Documentation update
- [ ] Performance improvement
- [ ] Code refactoring

## Related Issues

<!-- Укажите связанные issues -->

Closes #
Related to #

## Roadmap Reference

<!-- Если применимо, укажите раздел Roadmap -->

Roadmap §X.Y: 

## Changes Made

<!-- Детальное описание изменений -->

-
-
-

## Testing

### Test Coverage

- [ ] Unit tests added/updated
- [ ] Property tests added (если applicable)
- [ ] Integration tests added (если applicable)
- [ ] All existing tests pass

### Manual Testing

<!-- Опишите как вы тестировали изменения -->

**Test environment:**
- OS:
- Python version:
- Hardware:

**Test scenarios:**
1.
2.
3.

**Results:**
-

## Performance Impact

<!-- Если применимо, укажите performance changes -->

- [ ] No performance impact
- [ ] Performance improved (укажите benchmark results)
- [ ] Performance degraded (объясните почему acceptable)

**Benchmark results (если applicable):**
```
Before: X events/sec
After:  Y events/sec
Change: +Z%
```

## Breaking Changes

<!-- Если есть breaking changes, опишите их -->

- [ ] No breaking changes
- [ ] Breaking changes (опишите ниже)

**Breaking changes:**
-

**Migration guide:**
-

## Documentation

- [ ] Code comments updated
- [ ] README.md updated (если applicable)
- [ ] ADR created (для архитектурных решений)
- [ ] CHANGELOG.md updated
- [ ] API documentation updated (если applicable)

## ADR (Architecture Decision Record)

<!-- Если создан ADR, укажите -->

- [ ] No ADR needed
- [ ] ADR created: `docs/adr/ADR-XXX-title.md`

## Checklist

### Code Quality

- [ ] Code follows project style (ruff format + ruff check)
- [ ] No new warnings introduced
- [ ] Type hints added (для новых функций)
- [ ] Docstrings added (для public API)
- [ ] No hardcoded values (используйте constants/config)

### Security

- [ ] No secrets/credentials in code
- [ ] Input validation added (для user inputs)
- [ ] No SQL injection vulnerabilities
- [ ] Error messages don't leak sensitive info

### Capacity Measurement Safety

<!-- ВАЖНО для PR перед capacity measurement (2026-08-14) -->

- [ ] Does NOT change collector configuration
- [ ] Does NOT change storage layer (WAL/Parquet)
- [ ] Does NOT change feed scope
- [ ] Does NOT affect production deployment

**Если любой из пунктов выше = YES, ПОДОЖДИТЕ capacity measurement!**

## Deployment Notes

<!-- Инструкции для deployment, если нужны -->

- [ ] No special deployment steps
- [ ] Requires deployment steps (опишите ниже)

**Deployment steps:**
1.
2.

## Screenshots/Logs

<!-- Если applicable, добавьте screenshots или logs -->

## Reviewer Notes

<!-- Что нужно обратить особое внимание при review -->

**Focus areas:**
-

**Questions for reviewer:**
-

---

**Definition of Done:**
- [ ] All tests pass (local + CI)
- [ ] Code reviewed and approved
- [ ] Documentation updated
- [ ] No merge conflicts
- [ ] Ready to merge
