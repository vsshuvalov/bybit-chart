# Arbitrage PAPER Lab

Самостоятельный прототип проверки двух spot-стратегий на публичных данных
Bybit, Binance, OKX и Bitget:

- **межбиржевой арбитраж** — купить на одной площадке и продать на другой;
- **треугольный арбитраж** — выполнить внутри одной площадки цикл из трёх
  обменов `A → B → C → A`.

Все площадки равноправны. Межбиржевой движок считает исполнимую VWAP по
глубине стаканов в ручном режиме BTC/ETH/SOL. Режим `AUTO` получает публичные
spot-тикеры всех площадок, находит общие USDT-рынки, формирует пул из 150
самых ликвидных и одновременно проверяет до **50 наиболее волатильных** по
медианной абсолютной динамике за 24 часа. AUTO-PAPER начинает с 500 USDT на
каждой площадке. Чтобы редкое арбитражное окно не пришлось ждать без нужного
актива, PAPER-инвентарь заранее покупается из этих USDT для устойчиво входящих
в ликвидно-волатильный рейтинг пар. Это не считается арбитражной сделкой:
исполнение всё равно разрешено только при положительном net edge после двух
комиссий и risk buffer. В панели настраиваются лимит сделки, число и окно
наблюдений для активации, отдельный срок выхода, количество активных токенов,
сумма на токен, минимальный 24h-оборот и требуемая BBO-глубина. Значения по
умолчанию — 25 USDT, 5 наблюдений за 60 минут, выход после 60 минут, два токена
по 50 USDT, 1 млн USDT оборота на площадку и глубина 2 размера сделки. Панель и
API проверяют, что инвентарь вместе с одной сделкой помещается в исходные
500 USDT. Треугольный движок за один запрос
получает все spot-тикеры
площадки, выбирает до **50 ликвидных пар**, сохраняющих полные треугольники,
и проверяет оба направления каждого цикла с учётом трёх taker-комиссий,
top-of-book объёма и risk buffer.

Это только PAPER-система:

- API-ключи не принимаются;
- приватные endpoints отсутствуют;
- реальный ордер отправить невозможно;
- исполнения и балансы существуют только в памяти процесса.

## Быстрый запуск

```bash
cd /Users/vs/Desktop/Arbitrage
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m packages.api.app
```

Откройте:

- межбиржевой экран — [http://127.0.0.1:8000](http://127.0.0.1:8000);
- треугольный экран —
  [http://127.0.0.1:8000/triangular.html](http://127.0.0.1:8000/triangular.html);
- API-схему — [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

Один read-only скан из терминала:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/arbitrage/scan \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"AUTO","max_symbols":50,"notional":"40","activation_observations":3,"evidence_window_minutes":30,"inventory_idle_timeout_minutes":60,"max_active_symbols":3,"allocation_per_symbol_venue_usdt":"60","min_24h_volume_usdt":"1000000","bbo_depth_multiplier":"2","min_net_edge_bps":"5","risk_buffer_bps":"2","auto_execute":false}'
```

Скан треугольников по 50 ликвидным тикерам каждой площадки:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/triangular/scan \
  -H 'Content-Type: application/json' \
  -d '{"venue":"all","start_asset":"USDT","start_amount":"1000","max_tickers":50,"min_net_edge_bps":"5","risk_buffer_bps":"2","auto_execute":false}'
```

## Тесты

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
```

Подробная логика и ограничения:

- [`docs/ARBITRAGE_PAPER_PROTOTYPE.md`](docs/ARBITRAGE_PAPER_PROTOTYPE.md);
- [`docs/TRIANGULAR_ARBITRAGE_PAPER.md`](docs/TRIANGULAR_ARBITRAGE_PAPER.md).
