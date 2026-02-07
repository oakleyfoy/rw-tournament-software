import { useEffect } from 'react'
import { Routes, Route } from 'react-router-dom'
import TournamentList from './pages/TournamentList'
import TournamentSetup from './pages/TournamentSetup'
import DrawBuilder from './pages/DrawBuilder'
import ScheduleBuilderPage from './pages/ScheduleBuilderPage'
import SchedulePageGridV1 from './pages/schedule/SchedulePageGridV1'
import ScheduleEditorPage from './pages/schedule/editor/ScheduleEditorPage'
import MatchCardsPage, { MatchCardsRedirectToActive } from './pages/schedule/MatchCardsPage'
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
        <Route path="/tournaments/:id/schedule-builder" element={<ScheduleBuilderPage />} />
        <Route path="/tournaments/:id/schedule" element={<SchedulePageGridV1 />} />
        <Route path="/tournaments/:id/schedule/matches" element={<MatchCardsRedirectToActive />} />
        <Route path="/tournaments/:id/schedule/versions/:versionId/matches" element={<MatchCardsPage />} />
        <Route path="/tournaments/:id/schedule/editor" element={<ScheduleEditorPage />} />
        <Route path="/events/:eventId/who-knows-who" element={<WhoKnowsWho />} />
        <Route path="/settings" element={<Settings />} />
      </Routes>
    </div>
  )
}

export default App

