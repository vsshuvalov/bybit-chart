# Инструкция по запуску frontend

**После восстановления доступа к Bash выполните:**

```bash
cd /Users/vs/Desktop/bybit-chart/web
npm install
npm run dev
```

Приложение запустится на http://localhost:3000

**Важно:** Backend API должен работать на http://localhost:8000 (прокси настроен автоматически).

**Для запуска backend:**
```bash
cd /Users/vs/Desktop/bybit-chart
source .venv/bin/activate
python workers/api_server.py
```

---

## Что уже реализовано (Этап 7, первая итерация)

✅ Vite + React + TypeScript scaffold  
✅ Shell layout (top bar / left toolbar / center / right sidebar / bottom dock / status bar)  
✅ TopBar: symbol switcher (BTCUSDT/ETHUSDT/XRPUSDT), TF switcher (1m–1d), Live/Replay toggle  
✅ LeftToolbar: 14 drawing tools (cursor, trendline, ray, h/v, rectangle, ellipse, text, channel, fib, VWAP, VP, ruler, risk-reward)  
✅ RightSidebar: Watchlist (working) + DOM/Tape/Levels (placeholders)  
✅ Watchlist: 3 символа, Last/24h%/quality колонки, клик меняет symbol  
✅ BottomDock: Delta/CVD | OI/Funding | Strategy | Replay tabs (placeholders)  
✅ StatusBar: collector lag, analytics lag, gaps, release/config hashes  
✅ ChartPanel: lightweight-charts integration, OHLC candles с GET /api/v1/ohlc  
✅ TradingView-inspired dark theme  
✅ State management (Zustand): View, MarketData, UI stores  
✅ API client (Axios): все 10+ endpoints mapped  

---

## Следующие шаги

1. **Запустить и протестировать** — увидеть shell в браузере
2. **Добавить WebSocket** — live updates для candles/trades
3. **Реализовать DOM/Tape/Levels** — правый sidebar полностью
4. **Drawings persistence API** — GET/POST/PUT /api/v1/drawings + server storage
5. **Chart overlays** — indicators, Entry/SL/TP markers
6. **E2E tests** — Playwright (reload/TF round-trip, zoom, drawings survive restart)
