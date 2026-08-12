# Bybit Order Flow Platform — Frontend

**Tech Stack:** React 18 + TypeScript + Vite + lightweight-charts + Zustand + TanStack Query

**Status:** Scaffold complete, basic shell implemented

---

## Quick Start

```bash
cd web
npm install
npm run dev
```

App будет доступен на `http://localhost:3000`

Backend API должен работать на `http://localhost:8000` (прокси настроен в `vite.config.ts`).

---

## Structure

```
web/
├── src/
│   ├── components/
│   │   ├── TopBar.tsx          # Workspace, Symbol, TF, Live/Replay, Quality, Account
│   │   ├── LeftToolbar.tsx     # Drawing tools (14 инструментов)
│   │   ├── RightSidebar.tsx    # Watchlist / DOM / Tape / Levels tabs
│   │   ├── Watchlist.tsx       # BTCUSDT/ETHUSDT/XRPUSDT + Last/24h%/quality
│   │   ├── BottomDock.tsx      # Delta/CVD | OI/Funding | Strategy | Replay
│   │   ├── StatusBar.tsx       # Feed ages, gaps, analytics lag, release hashes
│   │   └── ChartPanel.tsx      # lightweight-charts OHLC candles
│   ├── api.ts                  # Axios client + API functions
│   ├── store.ts                # Zustand global state (View, MarketData, UI)
│   ├── App.tsx                 # Shell layout (§11.1)
│   ├── main.tsx                # Entry point
│   └── index.css               # Global CSS + theme variables
├── index.html
├── vite.config.ts
├── tsconfig.json
└── package.json
```

---

## State Management (Roadmap §11.7)

**View Store:** `useViewStore()`
- symbol, timeframe, environment, tradingState, isReplayMode
- Не очищается при unmount/TF change

**Market Data Store:** `useMarketDataStore()`
- OHLC candles per symbol+timeframe
- Recent trades, mark prices
- Не очищается при unmount

**UI Store:** `useUIStore()`
- Панельная видимость (left/right/bottom)
- Активная вкладка (rightSidebarTab, bottomDockTab)
- Активный drawing tool

---

## API Endpoints (proxied to :8000)

- `GET /api/v1/symbols` — список символов
- `GET /api/v1/trades` — raw trades (start_ts, end_ts, limit)
- `GET /api/v1/ohlc` — OHLC candles (symbol, interval, start_ts, end_ts)
- `GET /api/v1/analytics/delta` — Delta
- `GET /api/v1/analytics/cvd` — Cumulative Volume Delta
- `GET /api/v1/analytics/vwap` — VWAP
- `GET /api/v1/analytics/volume-profile` — Volume Profile
- `GET /api/v1/analytics/heatmap` — Orderbook heatmap
- `GET /api/v1/analytics/orderflow/regime` — Market regime
- `GET /api/v1/analytics/orderflow/features` — Orderflow features

---

## Implemented (Roadmap §11)

✅ **Shell layout** (§11.1): top bar, left toolbar, center chart, right sidebar, bottom dock, status bar  
✅ **TopBar** (§11.2): workspace, symbol, TF switcher (1m/5m/15m/30m/1h/4h/1d), Live/Replay toggle, Quality badge, environment, trading state  
✅ **LeftToolbar** (§11.3): 14 drawing tools (cursor, trendline, ray, h/v line, rectangle, ellipse, text, channel, fibonacci, anchored VWAP, VP, ruler, risk-reward), lock/hide/delete/clear actions  
✅ **RightSidebar** (§11.4): tab structure (Watchlist / DOM / Tape / Levels)  
✅ **Watchlist** (§11.4): BTCUSDT/ETHUSDT/XRPUSDT, Last/24h%/quality колонки, клик меняет symbol без reconnect  
✅ **BottomDock** (§11.1): Delta/CVD | OI/Funding | Strategy | Replay tabs  
✅ **StatusBar** (§11.1, §11.8): collector lag, analytics lag, gap count, release/config hashes — всегда видимы  
✅ **ChartPanel**: lightweight-charts integration, OHLC candles, TradingView-style dark theme  
✅ **State boundaries** (§11.7): View store (presentation), MarketData store (не очищается), UI store (layout)

---

## TODO (Roadmap §11)

- [ ] **Menus** (§11.5): schema-driven module settings (Indicators / Order Flow / Strategies / Replay)
- [ ] **Drawings persistence** (§11.3): server-side storage с schemaVersion + revision
- [ ] **DOM panel** (§11.4): bid/ask depth, cumulative, pulling/stacking
- [ ] **Tape panel** (§11.4): time/price/side/volume, BT/RPI flags
- [ ] **Levels panel** (§11.4): POC/VAH/VAL/VWAP/walls/user levels
- [ ] **Chart layers** (§11.1): overlay/separatePane indicators, z-order, Entry/SL/TP overlays
- [ ] **Diagnostics tooltip** (§11.8): Data Quality badge раскрытие (feed ages, gaps details)
- [ ] **Heatmap scope tooltip** (§11.8): явно показывает standard-only пока RPI не включён
- [ ] **WebSocket live updates**: WS connection для real-time candles/trades
- [ ] **E2E tests** (§11.8): Vitest + Playwright (reload/TF round-trip, zoom/DPI, drawings survive restart)

---

## Acceptance Criteria (Roadmap §11.8, §19)

- [ ] E2E reload/TF/symbol tests
- [ ] `1m → 5m → 15m → 1m` возвращает исходный checksum
- [ ] REST snapshot + WS buffer → без дублей
- [ ] Patch gap → resnapshot
- [ ] Canvas-coordinate tests для Sweep/Absorption/Walls
- [ ] Browser visual tests: zoom, перекрытия, DPI, читаемость
- [ ] Palette/theme/zoom не меняют Strategy Feature API
- [ ] Drawings survive restart/backup restore
- [ ] Quality/gap labels всегда видимы
- [ ] BTC/ETH/XRP switch не reconnect-ит Bybit
- [ ] Миграция/corruption local preferences не теряет server artifacts

---

## Development

**Install dependencies:**
```bash
cd web
npm install
```

**Start dev server:**
```bash
npm run dev
```

**Type check:**
```bash
npm run type-check
```

**Build for production:**
```bash
npm run build
npm run preview
```

---

## Notes

- **Theme:** TradingView-inspired dark (`--bg-primary: #131722`)
- **Chart library:** lightweight-charts v4.2.0 (TradingView's official chart library)
- **Proxy:** `/api` → `http://localhost:8000/api` (configured in vite.config.ts)
- **localStorage:** только для UI cache (theme/layout/последний view) — НЕ для drawings/workspaces (§11.7)
- **Server source of truth:** workspaces, drawings, scripts, orders, positions (§11.7)
