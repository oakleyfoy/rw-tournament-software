import { useEffect } from 'react'
import { Routes, Route } from 'react-router-dom'
import TournamentList from './pages/TournamentList'
import TournamentSetup from './pages/TournamentSetup'
import DrawBuilder from './pages/DrawBuilder'
import SchedulePageGridV1 from './pages/schedule/SchedulePageGridV1'
import WhoKnowsWho from './pages/WhoKnowsWho'
import Settings from './pages/Settings'
import { getCurrentTheme, applyTheme } from './utils/settings'

function App() {
  useEffect(() => {
    // Apply theme on mount
    const theme = getCurrentTheme()
    applyTheme(theme)
  }, [])

  return (
    <div className="App">
      <Routes>
        <Route path="/" element={<TournamentList />} />
        <Route path="/tournaments" element={<TournamentList />} />
        <Route path="/tournaments/:id/setup" element={<TournamentSetup />} />
        <Route path="/tournaments/:id/draw-builder" element={<DrawBuilder />} />
        <Route path="/tournaments/:id/schedule" element={<SchedulePageGridV1 />} />
        <Route path="/events/:eventId/who-knows-who" element={<WhoKnowsWho />} />
        <Route path="/settings" element={<Settings />} />
      </Routes>
    </div>
  )
}

export default App

