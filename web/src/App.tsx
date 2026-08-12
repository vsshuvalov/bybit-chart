/**
 * App Shell Layout (Roadmap §11.1).
 *
 * Structure:
 *   Top bar: workspace | symbol | TF | replay/live | quality | account
 *   Left toolbar: drawing tools
 *   Center: chart
 *   Right sidebar: Watchlist | DOM/Tape | Orders/Positions | AI
 *   Bottom dock: Delta/CVD | OI/Funding | Strategy log | Replay metrics
 *   Status bar: feed ages | gaps | analytics lag | release/config hashes
 */

import { useViewStore, useUIStore } from './store'
import TopBar from './components/TopBar'
import LeftToolbar from './components/LeftToolbar'
import RightSidebar from './components/RightSidebar'
import BottomDock from './components/BottomDock'
import StatusBar from './components/StatusBar'
import ChartPanel from './components/ChartPanel'

export default function App() {
  const { leftToolbarVisible, rightSidebarVisible, bottomDockVisible } = useUIStore()

  return (
    <div className="app-shell">
      <TopBar />

      <div className="app-body">
        {leftToolbarVisible && <LeftToolbar />}

        <div className="center-container">
          <ChartPanel />
          {bottomDockVisible && <BottomDock />}
        </div>

        {rightSidebarVisible && <RightSidebar />}
      </div>

      <StatusBar />

      <style>{`
        .app-shell {
          display: flex;
          flex-direction: column;
          width: 100vw;
          height: 100vh;
          overflow: hidden;
        }

        .app-body {
          display: flex;
          flex: 1;
          overflow: hidden;
        }

        .center-container {
          display: flex;
          flex-direction: column;
          flex: 1;
          overflow: hidden;
        }
      `}</style>
    </div>
  )
}
