# Интрадей-стратегии BTCUSDT на Bybit

## Техническая спецификация для Order Flow / Heatmap-платформы

**Версия:** 1.0  
**Дата повторной проверки:** 2026-08-08  
**Инструмент:** BTCUSDT Linear Perpetual, Bybit  
**Сетевая задержка:** RTT до 200 мс  
**Назначение:** разработка, event-driven бэктест и последующая автоматизация

> Параметры в документе являются стартовыми диапазонами для исследования, а не доказанными прибыльными настройками. Перед реальной торговлей каждая стратегия должна пройти replay, walk-forward, out-of-sample и paper trading с фактическими комиссиями и задержками.

---

## 1. Результат повторной проверки списка

Первоначальный список был концептуально правильным, но смешивал три разные сущности:

1. самостоятельные торговые стратегии;
2. подтверждающие Order Flow-признаки;
3. режимные фильтры.

После пересмотра остаются шесть самостоятельных production-моделей и один экспериментальный фильтр.

| Модель | Итоговый статус | Рыночный режим | Типичное удержание | RTT 200 мс |
|---|---|---|---:|---|
| Sweep Failure / Failed Auction | Основная | Range, level rejection | 1–15 минут | Подходит |
| Breakout Acceptance + Retest | Основная | Breakout, trend | 5–60 минут | Подходит |
| Trend Pullback | Основная | Trend | 5–120 минут | Подходит |
| VWAP / Value Area Re-entry and Rotation | Основная | Range | 5–120 минут | Подходит |
| Absorption Reversal без sweep | Основная | Range, reversal | 2–30 минут | Подходит |
| Liquidation Exhaustion | Условная, повышенный риск | Liquidation cascade | 30 секунд – 15 минут | Подходит после подтверждения |
| Liquidity Vacuum | Экспериментальный фильтр | Breakout, trend | 10 секунд – 3 минуты | Ограниченно |

### Исключённые самостоятельные стратегии

При RTT около 200 мс не следует создавать отдельные торговые движки для:

- прогнозирования следующего тика по microprice;
- MLOFI-скальпинга на десятках миллисекунд;
- queue-position и maker-скальпинга;
- немедленного входа на первом импульсе sweep;
- немедленного входа при исчезновении стены;
- одиночной CVD divergence;
- одиночного stacked imbalance;
- одного крупного принта;
- одиночного всплеска ликвидаций;
- funding или OI без реакции цены.

Microprice, OFI, MLOFI, CVD, imbalance, refill, liquidity pull, OI и funding остаются полезными признаками и фильтрами, но не самостоятельными точками входа.

---

## 2. Доступные данные и ограничения Bybit

### 2.1. Сделки

`publicTrade.BTCUSDT` передаёт сделки в реальном времени. В сообщении доступны:

- `T` — время исполнения;
- `S` — сторона taker;
- `v` — объём;
- `p` — цена;
- `i` — Trade ID;
- `seq` — cross sequence;
- `BT` и `RPI` — дополнительные признаки.

Несколько сообщений могут иметь одинаковый `seq`, поэтому дедупликация должна выполняться по:

```text
category + symbol + tradeId
```

[Официальная документация Public Trade](https://bybit-exchange.github.io/docs/v5/websocket/public/trade)

### 2.2. Стакан

Для linear-контрактов доступны:

| Глубина | Частота публикации |
|---:|---:|
| L1 | 10 мс, только snapshot |
| L50 | 20 мс |
| L200 | 100 мс |
| L1000 | 200 мс |

Рабочая конфигурация платформы может использовать:

```text
L50  → быстрые признаки ближайшей ликвидности
L200 → контекст и Heatmap средней глубины
L1000 → глубокий контекст, если оправданы нагрузка и хранение
```

Важные поля:

- `u` — update ID;
- `seq` — cross sequence;
- `cts` — время matching engine;
- `snapshot` требует полной замены локальной книги;
- `size=0` означает, что уровень был исполнен **или** отменён.

Следовательно, публичный стакан не позволяет абсолютно точно разделить `executed`, `cancelled` и `refilled`. Эти признаки должны называться оценочными и сопровождаться `attributionConfidence`.

RPI-заявки не входят в стандартный публичный order book. [Официальная документация Order Book](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook)

### 2.3. Ликвидации

`allLiquidation.BTCUSDT` публикуется каждые 500 мс.

Критически важная нормализация текущей спецификации Bybit:

```text
S=Buy  → ликвидирована long-позиция
S=Sell → ликвидирована short-позиция
```

Для стратегии удобно создать собственные поля:

```text
S=Buy  → liquidatedPositionSide=Long  → inferredForcedFlow=Sell
S=Sell → liquidatedPositionSide=Short → inferredForcedFlow=Buy
```

`p` является bankruptcy price и не обязан совпадать с фактической ценой сделки. Парсер должен принимать `data` как массив событий. [Официальная документация All Liquidation](https://bybit-exchange.github.io/docs/v5/websocket/public/all-liquidation)

### 2.4. Open Interest и funding

Ticker деривативов публикуется каждые 100 мс и содержит `openInterest`, `openInterestValue`, `fundingRate`, mark/index price и время следующего funding. Это snapshot/delta-поток: отсутствующее поле означает, что значение не изменилось, а не стало пустым.

Исторический OI Bybit имеет минимальный интервал 5 минут. Поэтому live OI для точного исследования нужно сохранять самостоятельно.

- [Ticker WebSocket](https://bybit-exchange.github.io/docs/v5/websocket/public/ticker)
- [Open Interest REST](https://bybit-exchange.github.io/docs/v5/market/open-interest)
- [Funding History](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate)

OI и funding используются как режимные фильтры. Они не определяют направление сделки без реакции цены и Order Flow.

---

## 3. Обязательные модули

```text
MarketDataCollector
MarketDataQuality
TradeNormalizer
TradeDeduplicator
OrderBookReconstructor
Heatmap
Footprint
Delta + CVD
VWAP
Volume Profile
LevelEngine
OFI / MLOFI / Microprice
AttributionEngine
LiquidationAggregator
RegimeClassifier
FeatureStore
LevelInteractionClassifier
StrategyEngine
RiskManager
ExecutionEngine
Order/Position Reconciliation
Event-driven Replay
Telemetry
```

### Состояния качества данных

```text
BOOTSTRAP
LIVE_READY
DEGRADED
STALE
GAP
REBUILDING
```

Новые входы разрешены только в `LIVE_READY`. В остальных состояниях разрешены:

- сопровождение уже открытой позиции;
- установка или восстановление защитного SL;
- безопасное сокращение или закрытие позиции.

---

## 4. Общие определения

### Delta

```text
TradeSign = +1 для taker Buy
TradeSign = -1 для taker Sell

Delta = sum(TradeSign × Quantity)
```

### CVD

```text
CVD[n] = CVD[n - 1] + Delta[n]
```

Якорь CVD должен быть явным и входить в ключ кеша:

- UTC day;
- торговая сессия;
- фиксированное событие;
- выбранный диапазон;
- continuous.

### Robust Z-score

Для объёма, Delta и ликвидаций предпочтителен устойчивый Z-score:

```text
RobustZ(x) = (x - Median) / (1.4826 × MAD)
```

Расчёт должен использовать только прошлые данные. Базовые распределения желательно разделять по времени суток и режиму волатильности.

### Price Impact Efficiency

```text
ImpactEfficiency =
    abs(PriceDisplacementTicks)
    / max(AggressiveVolume, epsilon)
```

Большой агрессивный объём при низкой эффективности может указывать на поглощение.

### Оценочный refill

```text
EstimatedRefillRatio =
    RestoredPassiveLiquidity
    / max(EstimatedExecutedPassiveLiquidity, epsilon)
```

Поскольку стакан сам не различает исполнение и отмену, вместе с метрикой обязательно хранится:

```text
attributionConfidence ∈ [0, 1]
```

Ни один refill/cancel-признак не должен запускать сделку при низкой уверенности.

### Риск R

После фактического исполнения входа:

```text
R = abs(AverageFillPrice - HardStopPrice)
```

Все TP и ограничения погони за ценой пересчитываются от фактической средней цены исполнения, а не от цены первоначального сигнала.

---

## 5. Классификация режима рынка

Перед выбором стратегии рынок классифицируется как:

```text
RANGE
TREND_UP
TREND_DOWN
BREAKOUT
LIQUIDATION_CASCADE
LOW_LIQUIDITY
ABNORMAL_SPREAD
UNKNOWN
```

### Пример признаков RANGE

- небольшой нормализованный наклон VWAP;
- POC остаётся в одной зоне;
- частые возвраты внутрь Value Area;
- пробои VAH/VAL не получают acceptance;
- цена вращается вокруг VWAP.

### Пример признаков TREND

- устойчивый наклон VWAP;
- последовательность higher high / higher low или lower high / lower low;
- POC и Value Area мигрируют по направлению;
- откаты имеют меньшую эффективность, чем импульсы;
- CVD не демонстрирует устойчивое сильное противоречие.

### Разрешённые стратегии

| Режим | Разрешённые модели |
|---|---|
| RANGE | Sweep Failure, Absorption Reversal, VWAP/Value Area Rotation |
| TREND | Trend Pullback, Breakout Retest |
| BREAKOUT | Breakout Acceptance + Retest |
| LIQUIDATION_CASCADE | Liquidation Exhaustion после подтверждения |
| LOW_LIQUIDITY | Новые входы запрещены |
| ABNORMAL_SPREAD | Новые входы запрещены |
| UNKNOWN | Новые входы запрещены или минимальный риск |

---

## 6. Универсальный автомат стратегии

```text
DISABLED
→ SCANNING
→ SETUP_FOUND
→ WAITING_CONFIRMATION
→ WAITING_ENTRY
→ ORDER_PENDING
→ POSITION_OPEN
→ MANAGED
→ CLOSED / INVALIDATED / ERROR
```

Необходимо различать:

1. `setup invalidation` — отмена сигнала до входа;
2. `entry expiration` — сигнал устарел до исполнения;
3. `logic exit` — досрочный выход после входа;
4. `hard SL` — серверная защита от катастрофического движения;
5. `time stop` — выход, если ожидаемая реакция не появилась;
6. `TP` — плановая фиксация прибыли.

Каждый сигнал должен сохранять:

```typescript
interface StrategySignal {
  signalId: string;
  strategyId: string;
  strategyVersion: string;
  configurationVersion: string;

  detectedAtMs: number;
  expiresAtMs: number;
  side: "Long" | "Short";

  referenceLevelTicks: bigint;
  proposedEntryTicks: bigint;
  proposedStopTicks: bigint;
  proposedTargetTicks: bigint[];

  featureSnapshot: Record<string, number | string | boolean>;
  attributionConfidence: number;
  marketDataQuality: Record<string, number | string | boolean>;
}
```

После рестарта сигнал с истёкшим `expiresAtMs` не восстанавливается для исполнения.

---

## 7. Задержка и общие запреты

Ориентироваться нужно не на ICMP ping, а на фактические распределения:

```text
marketDataAge
signalToSend
orderAckRTT
signalToFill
```

Правило для RTT около 200 мс:

```text
ExpectedSignalEdgeLifetime
≥ 5 × p99(signalToFill)
```

Стартовые ограничения:

```yaml
data_quality:
  max_trade_age_ms: 400
  max_book_age_ms: 400
  max_book_trade_skew_ms: 300
  warmup_after_snapshot_ms: 3000
  reject_unresolved_gap: true

latency:
  max_signal_to_fill_p99_ms: 800
  minimum_confirmation_ms: 1500
  preferred_confirmation_ms: 2000-5000
  minimum_expected_holding_ms: 30000
```

Общий запрет входа:

```yaml
no_trade_if:
  data_quality_not_live_ready: true
  unresolved_gap: true
  insufficient_warmup: true
  abnormal_spread: true
  attribution_confidence_below: 0.65
  net_reward_risk_below: 1.40
  signal_expired: true
  stop_distance_invalid: true
```

---

## 8. Исполнение, SL, TP и риск

### Вход

Для подтверждённых моделей предпочтителен marketable limit IOC с ограничением проскальзывания. Обычную market-заявку Bybit также преобразует в IOC limit и может отменить полностью или частично при отсутствии ликвидности в допустимом диапазоне.

```yaml
execution:
  entry_type: marketable_limit_ioc
  entry_ttl_ms: 3000
  require_private_fill_confirmation: true
  require_server_side_hard_stop: true
  take_profit_reduce_only: true
  do_not_chase_above_r: 0.10
```

REST-ответ на создание заявки подтверждает принятие запроса, но не исполнение. Фактический order status и fills подтверждаются private `order` и `execution` WebSocket.

- [Place Order](https://bybit-exchange.github.io/docs/v5/order/create-order)
- [Private Order Stream](https://bybit-exchange.github.io/docs/v5/websocket/private/order)
- [Private Execution Stream](https://bybit-exchange.github.io/docs/v5/websocket/private/execution)

### Hard Stop Loss

Сразу после подтверждённого fill должен существовать server-side SL.

Структурный буфер:

```text
B = max(
    3 × tickSize,
    2 × spreadP95,
    microNoiseP95,
    k × ATR_1m
)
```

Стартовый диапазон:

```text
k = 0.05–0.15
k = 0.15–0.25 для liquidation strategy
```

`tickSize`, `qtyStep`, min notional и ограничения объёма необходимо получать динамически через Instruments Info. Bybit предупреждает, что некоторые максимальные размеры заявок пересматриваются регулярно. [Instruments Info](https://bybit-exchange.github.io/docs/v5/market/instrument)

### TP и trailing

Bybit поддерживает Full и Partial TP/SL, триггеры `LastPrice`, `MarkPrice`, `IndexPrice` и server-side trailing. В режиме Partial значения `tpSize` и `slSize` одной пары должны совпадать. Для нескольких TP можно использовать несколько partial-пар или отдельные `reduceOnly` exit-заявки; остаточные заявки необходимо отменять явно. [Set Trading Stop](https://bybit-exchange.github.io/docs/v5/position/trading-stop)

### Перенос в безубыток

После TP1 стоп не переносится автоматически в точный Entry. Перенос выполняется только после структурного подтверждения:

```text
Long BE  = AverageFillPrice + подтверждённые издержки
Short BE = AverageFillPrice - подтверждённые издержки
```

### Размер позиции

```text
RiskUSDT =
    EquityUSDT
    × RiskPercent
    × StrategyRiskMultiplier

RiskPerBTC =
    abs(AverageFillPrice - StopPrice)
    + EntryFeePerBTC
    + ExpectedExitFeePerBTC
    + SlippageAllowancePerBTC

QuantityBTC = RiskUSDT / RiskPerBTC
```

Реальные комиссии аккаунта нужно запрашивать через [Account Fee Rate](https://bybit-exchange.github.io/docs/v5/account/fee-rate), а не фиксировать в коде.

Стартовые ограничения риска:

```yaml
risk:
  base_risk_per_trade_pct: 0.25
  maximum_risk_per_trade_pct: 0.50
  maximum_daily_loss_pct: 1.00
  maximum_consecutive_losses: 3
  maximum_positions_per_symbol: 1
  averaging_down: false
  martingale: false
```

---

## 9. Sweep Failure / Failed Auction

### 9.1. Идея

Цена пробивает очевидный уровень, активирует стопы и привлекает пробойных участников, но не получает продолжения. Затем цена возвращается за уровень и оставляет поздних участников в ловушке.

Источники уровней:

- session high/low;
- previous day high/low;
- локальный swing high/low;
- VAH/VAL;
- LVN;
- крупная зона Footprint;
- устойчивая зона Heatmap.

### 9.2. Long setup

1. Цена проходит ниже поддержки.
2. Sell Delta и агрессивные продажи аномальны относительно режима.
3. Дальнейшее падение становится неэффективным.
4. Возможны ликвидации long-позиций, нормализованные из `S=Buy`.
5. Цена возвращается выше уровня за 1–5 секунд.
6. Удерживается выше 1.5–3 секунды.
7. Выполняется успешный ретест сверху.
8. Delta меняется в положительную сторону или пробивается post-sweep micro-swing high.
9. Выполняется вход marketable limit IOC.

Short setup полностью зеркален.

### 9.3. Отмена до входа

- reclaim не произошёл в заданное время;
- цена принята за уровнем;
- экстремум продолжает обновляться;
- ретест не состоялся или оказался слишком глубоким;
- возник unresolved gap или stale data;
- ближайшая цель не обеспечивает минимальный net RR;
- signal-to-fill стал слишком большим относительно жизни сигнала.

### 9.4. Stop Loss

```text
Long SL  = SweepLow - B
Short SL = SweepHigh + B
```

Logic exit до hard SL:

- повторное принятие цены за sweep-уровнем;
- повышенный объём за уровнем в течение 2–3 секунд;
- восстановление эффективного агрессивного движения против позиции.

### 9.5. Take Profit

```text
TP1: 30% — 1R или ближайший micro-swing
TP2: 40% — VWAP/POC или 2R
TP3: 30% — следующая крупная зона либо trailing по структуре
```

Если сильная противоположная ликвидность расположена раньше 1R, сделка пропускается.

### 9.6. Time stop

- нет минимум `0.5R` за 60–120 секунд — сократить или закрыть;
- максимальное удержание — 15 минут, если позиция не перешла в подтверждённое трендовое сопровождение.

### 9.7. Стартовая конфигурация

```yaml
sweep_failure:
  enabled: true
  risk_multiplier: 1.0

  sweep:
    aggressive_volume_robust_z: 2.0
    delta_robust_z: 2.0
    minimum_levels_crossed: 3

  confirmation:
    max_reclaim_time_ms: 5000
    min_hold_after_reclaim_ms: 1500
    require_retest: true
    require_delta_flip_or_micro_break: true

  management:
    logic_acceptance_ms: 2500
    time_stop_ms: 120000
    maximum_holding_ms: 900000
```

---

## 10. Breakout Acceptance + Retest

### 10.1. Идея

Это парная стратегия к Sweep Failure. Уровень не отвергается, а принимается рынком: ликвидность действительно поглощается сделками, цена удерживается снаружи и формирует объём за границей старого диапазона.

Для одного события `Sweep Failure` и `Breakout Acceptance` должны быть взаимоисключающими.

### 10.2. Long setup

1. Цена подходит к сопротивлению.
2. На уровне проходит подтверждённый агрессивный Buy volume.
3. Buy Delta и общий объём выше нормы.
4. Цена проходит сопротивление.
5. За уровнем формируется traded volume.
6. Цена удерживается выше 3–15 секунд.
7. Выполняется ретест.
8. Продажи не принимают цену обратно внутрь старого диапазона.
9. Появляется подтверждение Bid и возобновление покупок.
10. Вход выполняется после ретеста, а не на первой пробойной свече.

Short setup зеркален.

### 10.3. Отмена до входа

- стена исчезла без достаточного подтверждённого traded volume;
- `attributionConfidence` слишком низкая;
- цена вернулась внутрь диапазона;
- ретест прошёл слишком глубоко;
- цена уже прошла большую часть ожидаемого движения;
- следующая сильная ликвидность слишком близка;
- spread или market-data age вышли за лимит.

### 10.4. Stop Loss

```text
Long SL  = RetestLow - B
Short SL = RetestHigh + B
```

Для Long стоп должен находиться за breakout level. Если это создаёт чрезмерно широкий риск, сделка пропускается.

Logic exit:

- принятие цены внутри старого диапазона 2–5 секунд;
- повышенный traded volume внутри диапазона;
- исчезновение поддерживающей ликвидности с высокой уверенностью.

### 10.5. Take Profit

```text
TP1: 25–30% — 1R или первая противоположная ликвидность
TP2: 40% — 2R или следующий Profile/Heatmap-уровень
TP3: 30–35% — measured move или trailing по структуре
```

```text
Long Measured Move  = BreakoutLevel + HeightOfPriorRange
Short Measured Move = BreakoutLevel - HeightOfPriorRange
```

TP перед Heatmap-стеной размещается с небольшим отступом, определяемым тестами исполнения.

### 10.6. Time stop

- нет `0.5R` за 2–5 минут — закрыть;
- максимальное удержание — 60 минут.

### 10.7. Стартовая конфигурация

```yaml
breakout_retest:
  enabled: true
  risk_multiplier: 1.0

  breakout:
    volume_robust_z: 2.0
    delta_robust_z: 1.5
    minimum_attribution_confidence: 0.70

  acceptance:
    minimum_hold_outside_ms: 3000
    maximum_confirmation_ms: 15000
    maximum_retest_wait_ms: 30000
    require_traded_volume_outside: true

  management:
    logic_acceptance_inside_ms: 3000
    time_stop_ms: 300000
    maximum_holding_ms: 3600000
```

---

## 11. Trend Pullback

### 11.1. Идея

Стратегия не пытается предсказывать разворот. Она ожидает коррекцию к структурному уровню внутри уже подтверждённого тренда и входит только после завершения отката.

### 11.2. Контекст Long

- цена выше anchored/session VWAP;
- VWAP имеет устойчивый положительный наклон;
- структура формирует higher high / higher low;
- POC или Value Area мигрируют вверх;
- импульсы эффективнее откатов;
- CVD не демонстрирует устойчивое сильное противоречие.

### 11.3. Long setup

1. Цена откатывает к VWAP, POC, HVN или предыдущему breakout level.
2. На откате появляется отрицательная Delta.
3. Цена не пробивает последний higher low.
4. Возникает absorption или оценочный refill с достаточной уверенностью.
5. Delta снова становится положительной.
6. Пробивается micro-swing high.
7. Вход выполняется на пробое или контролируемом ретесте.

Short setup зеркален.

### 11.4. Отмена до входа

- потерян последний структурный higher low/lower high;
- цена принята за опорным уровнем;
- VWAP/POC перестали подтверждать тренд;
- режим сменился на range;
- предыдущий экстремум расположен слишком близко и не обеспечивает net RR.

### 11.5. Stop Loss

```text
Long SL  = PullbackLow - B
Short SL = PullbackHigh + B
```

Если структурный стоп превышает допустимую долю ATR или риск-лимит, сделка пропускается. Нельзя искусственно приближать SL ради увеличения размера позиции.

### 11.6. Take Profit

```text
TP1: 30% — предыдущий trend extreme или 1R
TP2: 40% — следующая зона либо 2R
TP3: 30% — trailing по подтверждённым higher low / lower high
```

Trailing включается после обновления предыдущего экстремума, а не сразу после входа.

### 11.7. Time stop

- нет `0.5R` за 3–5 минут — закрыть;
- максимальное удержание — 60–120 минут в зависимости от сессии и режима.

### 11.8. Стартовая конфигурация

```yaml
trend_pullback:
  enabled: true
  risk_multiplier: 1.0

  trend:
    require_vwap_slope: true
    require_market_structure: true
    require_value_migration: true
    require_cvd_non_conflict: true

  pullback:
    allowed_levels: [vwap, poc, hvn, previous_breakout]
    require_delta_flip: true
    require_microstructure_break: true

  management:
    time_stop_ms: 300000
    maximum_holding_ms: 7200000
```

---

## 12. VWAP / Value Area Re-entry and Rotation

### 12.1. Идея

Это не вход при простом касании VWAP-полосы. Стратегия торгует неудачный выход из области стоимости и подтверждённый возврат внутрь Value Area.

Разрешена только в `RANGE`.

### 12.2. Long setup

1. Цена выходит ниже VAL или нижней VWAP-полосы.
2. Sell Delta остаётся высокой.
3. Price impact продаж снижается.
4. Цена возвращается внутрь Value Area.
5. Удерживается внутри 3–10 секунд.
6. Выполняется успешный ретест VAL.
7. Вход после подтверждения.

Short setup зеркален у VAH.

Delta divergence и absorption могут усиливать сигнал, но не обязательны одновременно.

### 12.3. Отмена до входа

- рынок формирует новую стоимость за VAL/VAH;
- цена удерживается снаружи на повышенном объёме;
- VWAP ускоренно наклоняется по направлению выхода;
- POC начинает мигрировать за старую Value Area;
- режим сменился с range на trend/breakout.

### 12.4. Stop Loss

```text
Long SL  = ExcursionLow - B
Short SL = ExcursionHigh + B
```

Статистическая VWAP-полоса является фильтром, но не заменяет структурный stop.

Logic exit:

- повторный выход из Value Area;
- acceptance снаружи 5–15 секунд;
- формирование нового объёма и миграция POC за границей.

### 12.5. Take Profit

```text
TP1: 30% — граница Value Area или первая VWAP-полоса
TP2: 50% — VWAP или POC
TP3: 20% — противоположная граница Value Area
```

Фактический порядок VWAP и POC определяется их положением на момент входа.

### 12.6. Time stop

- нет ожидаемого продвижения за 5–10 минут — закрыть;
- максимальное удержание — 60–120 минут;
- обязательный выход при подтверждённой смене режима.

### 12.7. Стартовая конфигурация

```yaml
value_area_rotation:
  enabled: true
  risk_multiplier: 0.8-1.0
  required_regime: RANGE

  profile:
    value_area_percent: 70
    anchor: utc_session

  entry:
    require_value_area_reentry: true
    minimum_reentry_hold_ms: 3000
    maximum_reentry_hold_ms: 10000
    require_retest: true

  management:
    acceptance_outside_ms: 10000
    time_stop_ms: 600000
    maximum_holding_ms: 7200000
```

---

## 13. Absorption Reversal без sweep

### 13.1. Граница стратегии

Absorption является самостоятельной стратегией только тогда, когда уровень не был существенно пробит.

Если absorption возникла внутри Sweep Failure, она считается подтверждающим признаком Sweep Failure. Вторая стратегия и вторая позиция не создаются.

### 13.2. Идея

Большой агрессивный объём проходит в узкой зоне, но перестаёт эффективно двигать цену. Пассивная сторона принимает поток, затем локальная структура ломается в обратном направлении.

```text
Высокий агрессивный объём
+ низкий price impact
+ несколько эпизодов оценочного refill
+ Delta flip
+ microstructure break
```

### 13.3. Long setup

1. Цена приходит в значимую поддержку.
2. Агрессивные продажи проходят в узкой ценовой зоне.
3. Sell Delta имеет аномальное значение.
4. Цена не продвигается вниз или продвигается неэффективно.
5. Наблюдается несколько эпизодов предполагаемого refill.
6. `attributionConfidence` остаётся выше минимального порога.
7. Delta меняется в положительную сторону.
8. Пробивается локальный micro-swing high.
9. Вход выполняется на пробое или ретесте.

Short setup зеркален.

### 13.4. Отмена до входа

- цена эффективно проходит absorption-зону;
- ImpactEfficiency снова растёт против предполагаемой сделки;
- attribution confidence недостаточна;
- нет слома структуры в заданное время;
- уровень фактически перешёл в breakout acceptance.

### 13.5. Stop Loss

```text
Long SL  = AbsorptionZoneLow - B
Short SL = AbsorptionZoneHigh + B
```

Logic exit:

- оценочный refill исчез;
- цена принимается за зоной 2–3 секунды;
- агрессивный поток снова эффективно двигает цену против позиции.

### 13.6. Take Profit

```text
TP1: 30% — 1R или ближайший swing
TP2: 40% — VWAP/POC или 2R
TP3: 30% — следующая Profile/Heatmap-зона или trailing
```

### 13.7. Time stop

- нет `0.5R` за 2–5 минут — закрыть;
- максимальное удержание — 30 минут.

### 13.8. Стартовая конфигурация

```yaml
absorption_reversal:
  enabled: true
  risk_multiplier: 0.8-1.0

  observation:
    window_ms: 10000
    aggressive_volume_robust_z: 2.0
    delta_robust_z: 2.0
    maximum_impact_efficiency_percentile: 20
    minimum_estimated_refill_events: 3
    minimum_attribution_confidence: 0.70

  confirmation:
    require_delta_flip: true
    require_microstructure_break: true
    maximum_confirmation_ms: 5000

  management:
    logic_acceptance_ms: 2500
    time_stop_ms: 300000
    maximum_holding_ms: 1800000
```

---

## 14. Liquidation Exhaustion

### 14.1. Статус

Контртрендовая событийная модель с повышенным риском. Она не пытается поймать первую волну каскада и активируется только после подтверждения истощения.

### 14.2. Long setup после ликвидаций long-позиций

1. В потоке Bybit наблюдается всплеск `S=Buy`, нормализованный как liquidation of long positions.
2. Предполагаемое forced flow направлено вниз.
3. Sell Delta резко отрицательная.
4. Цена ускоряется вниз.
5. Затем интенсивность ликвидаций снижается.
6. Новые продажи перестают обновлять минимум.
7. Возникает absorption с достаточной уверенностью.
8. Цена возвращается выше основания последнего импульса.
9. Выполняется удержание или успешный ретест.
10. Только после этого выполняется Long.

Short setup зеркален после ликвидаций short-позиций (`S=Sell`).

### 14.3. Запрещённый вариант

```text
Первый всплеск ликвидаций → немедленный контртрендовый вход
```

Каскад может продолжаться значительно дольше ожидаемого.

### 14.4. Отмена до входа

- интенсивность ликвидаций снова растёт;
- экстремум продолжает обновляться;
- spread аномально расширяется;
- восстановленная ликвидность исчезает;
- поток liquidation устарел или содержит gap;
- нет reclaim/hold в заданное время.

### 14.5. Stop Loss

```text
Long SL  = CascadeLow - max(B, 0.15–0.25 × ATR_1m)
Short SL = CascadeHigh + max(B, 0.15–0.25 × ATR_1m)
```

### 14.6. Take Profit

Ликвидационный разворот часто является отскоком, а не новым трендом, поэтому прибыль фиксируется быстрее:

```text
TP1: 40% — 0.8–1R или 25% retracement импульса
TP2: 35% — 50% retracement или POC
TP3: 25% — VWAP, начало каскада или 2–2.5R
```

### 14.7. Time stop

- нет быстрого отскока за 30–120 секунд — закрыть;
- максимальное удержание — 15 минут.

### 14.8. Стартовая конфигурация

```yaml
liquidation_exhaustion:
  enabled: true
  risk_multiplier: 0.50

  cascade:
    aggregation_window_ms: 3000
    liquidation_volume_robust_z: 3.0
    delta_robust_z: 2.5

  confirmation:
    require_liquidation_rate_decline: true
    minimum_failed_extreme_events: 2
    require_absorption: true
    require_reclaim: true
    minimum_reclaim_hold_ms: 1500

  management:
    time_stop_ms: 120000
    maximum_holding_ms: 900000
```

---

## 15. Liquidity Vacuum

### 15.1. Итоговый статус

```yaml
liquidity_vacuum:
  enabled_by_default: false
  role: experimental_filter
```

Liquidity Vacuum не считается самостоятельной production-стратегией при RTT 200 мс. Исчезновение ликвидности может быть исполнением, отменой или перестановкой заявок, а преимущество непосредственного входа живёт слишком мало.

Допустимо использовать его как дополнительный фильтр для:

- Breakout Acceptance + Retest;
- Trend Pullback continuation.

### 15.2. Исследовательский setup

1. Ask depth устойчиво уменьшается.
2. Buy Delta сохраняется.
3. Spread не расширяется аномально.
4. Первоначальный импульс уже произошёл.
5. Цена формирует базу 2–5 секунд.
6. Ликвидность впереди не восстанавливается.
7. Вход допускается только после пробоя или ретеста базы без погони за ценой.

### 15.3. Отмена

- Ask быстро восстанавливается;
- Bid снимается;
- spread расширяется;
- база пробивается вниз;
- attribution confidence низкая;
- срок жизни преимущества меньше `5 × p99(signalToFill)`.

### 15.4. Исследовательское управление

```text
SL: BaseLow - B для Long
TP1: 50% перед следующей устойчивой Ask-зоной
TP2: 30% на 1.5–2R
TP3: 20% trailing
Time stop: 15–60 секунд
Maximum holding: 2–3 минуты
Risk multiplier: 0.50
```

До прохождения отдельного out-of-sample теста модуль должен оставаться выключенным.

---

## 16. Level Interaction Classifier

Для предотвращения двойных сигналов взаимодействие с одним уровнем классифицируется единожды:

```text
Цена подошла к уровню
        │
        ├── уровень не пробит, поток поглощён
        │       → Absorption Reversal
        │
        ├── уровень пробит, затем reclaim
        │       → Sweep Failure
        │
        └── уровень пробит, сформирован acceptance и retest
                → Breakout Acceptance + Retest
```

Правила:

- одному `levelInteractionId` соответствует максимум одна активная позиция;
- absorption внутри sweep является feature, а не второй стратегией;
- liquidation event может менять score/risk, но не создаёт дублирующую позицию;
- после классификации события альтернативные стратегии переводятся в `INVALIDATED`;
- повторный сигнал разрешается только после окончания cooldown или формирования нового независимого interaction ID.

---

## 17. Контекстные признаки, не являющиеся входом

### CVD divergence

Используется для повышения или понижения score. Без реакции цены, уровня и подтверждения не является входом.

### Stacked imbalance

Показывает концентрацию агрессии, но не доказывает продолжение. Сильный imbalance может завершиться absorption.

### OFI/MLOFI и microprice

При RTT 200 мс используются для:

- оценки краткосрочного давления;
- подтверждения ретеста;
- фильтрации неблагоприятного входа;
- оценки вероятного проскальзывания.

Они не используются для next-tick стратегии.

### OI

Возможные интерпретации являются только гипотезами:

```text
Price ↑ + OI ↑ → возможное открытие новых позиций
Price ↑ + OI ↓ → возможное закрытие short
Price ↓ + OI ↑ → возможное открытие новых short
Price ↓ + OI ↓ → возможное закрытие long
```

По агрегированному OI нельзя точно определить владельца и намерение позиции.

### Funding

Используется для оценки перегруженности одной стороны и режима рынка. Высокий funding сам по себе не является контртрендовым входом.

---

## 18. Разрешение конфликтов

Если несколько модулей дают сигнал одновременно:

1. Проверяется `marketDataQuality`.
2. Определяется `regime`.
3. Определяется `levelInteractionId`.
4. Выбирается одна стратегия, разрешённая данным режимом.
5. Проверяется net RR после ожидаемых издержек.
6. Применяется наименьший допустимый risk multiplier.
7. Создаётся одна позиция на BTCUSDT.

Пример:

```text
Sweep ниже VAL
+ liquidation of longs
+ absorption
+ reclaim VAL

Основная стратегия: Sweep Failure
Контекст: Liquidation Exhaustion
Feature: Absorption
Risk multiplier: min(1.0, 0.5) = 0.5
Количество позиций: 1
```

---

## 19. Порядок разработки

### Этап 1. Level Interaction Classifier

Реализовать как единую пару:

1. Sweep Failure;
2. Breakout Acceptance + Retest.

Они классифицируют противоположные исходы взаимодействия с уровнем.

### Этап 2. Trend Pullback

Использовать уже готовые уровни, Delta, absorption features и regime classifier.

### Этап 3. VWAP / Value Area Rotation

Добавить строгую блокировку при trend/breakout режиме.

### Этап 4. Standalone Absorption Reversal

Absorption feature должен существовать с этапа 1, но отдельный торговый движок запускается только для события без sweep.

### Этап 5. Liquidation Exhaustion

Добавить после проверки нормализации стороны Bybit и качества liquidation history.

### Этап 6. Liquidity Vacuum

Только экспериментально и с `enabled=false` по умолчанию.

---

## 20. Event-driven бэктест

Бэктест должен воспроизводить тот же поток событий и те же версии feature engine, что live-система.

Обязательно моделировать:

- raw trades;
- snapshot/delta order book;
- sequence и gaps;
- late events и data revisions;
- реальные распределения market-data age;
- задержку signal-to-fill минимум 200–500 мс;
- отдельные всплески до наблюдаемого p99;
- spread;
- комиссии аккаунта;
- slippage;
- marketable limit IOC;
- partial fills;
- отмену остатка;
- отсутствие lookahead;
- server-side stop logic;
- time stop;
- logic exit;
- смену рыночного режима.

### Метрики

Для каждой стратегии и режима отдельно:

```text
Signals detected
Signals invalidated before entry
Orders submitted
Fill rate
Partial fill rate
Average and p95 slippage
Gross expectancy
Net expectancy
Profit factor
Win rate
Average win / average loss
MAE / MFE
Time to TP1
Time to hard SL
Time stop frequency
Logic exit frequency
Maximum drawdown
Exposure time
Results by UTC session
Results by volatility regime
```

### Инженерные критерии допуска

Стратегия не переводится в paper/live, если:

- результат положительный только без комиссий;
- преимущество исчезает при задержке 200–500 мс;
- большая часть прибыли создана несколькими выбросами;
- параметры нестабильны на соседних значениях;
- есть lookahead через окончательные бары или исправленные данные;
- fill model предполагает недоступную цену;
- стратегия требует точного определения cancel/refill при низкой уверенности;
- нет отдельной статистики по режимам;
- отсутствует out-of-sample период.

---

## 21. Paper trading и запуск

Рекомендуемая последовательность:

```text
Deterministic replay
→ unit/invariant tests
→ event-driven backtest
→ walk-forward
→ out-of-sample
→ live signal-only
→ paper execution
→ минимальный размер позиции
→ постепенное увеличение только после подтверждения статистики
```

Перед каждым входом журналируются:

- полная версия стратегии и конфигурации;
- снимок признаков;
- regime;
- market-data quality;
- signal age;
- expected/actual slippage;
- proposed и actual Entry;
- hard SL;
- TP1/TP2/TP3;
- рассчитанный размер позиции;
- причина отмены или исполнения.

---

## 22. Итог

Финальное production-ядро состоит из шести моделей:

1. Sweep Failure / Failed Auction.
2. Breakout Acceptance + Retest.
3. Trend Pullback.
4. VWAP / Value Area Re-entry and Rotation.
5. Absorption Reversal без sweep.
6. Liquidation Exhaustion.

`Liquidity Vacuum` остаётся экспериментальным фильтром и выключена по умолчанию.

Архитектурно первые три исхода взаимодействия с уровнем должны классифицироваться совместно:

```text
не пробили уровень     → Absorption Reversal
пробили и вернулись    → Sweep Failure
пробили и приняли цену → Breakout Acceptance + Retest
```

Это предотвращает дублирующие сигналы и создаёт единое основание для будущей стратегии. При RTT около 200 мс преимущество должно формироваться не из скорости реакции на следующий тик, а из подтверждённой реакции рынка, удержания уровня, ретеста и корректного управления риском.
