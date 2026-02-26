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
import PublicDrawsPage from './pages/public/PublicDrawsPage'
import PublicWaterfallPage from './pages/public/PublicWaterfallPage'
import PublicBracketPage from './pages/public/PublicBracketPage'
import PublicRoundRobinPage from './pages/public/PublicRoundRobinPage'
import PublicSchedulePage from './pages/public/PublicSchedulePage'
import TournamentDeskPage from './pages/desk/TournamentDeskPage'
import TournamentDeskBoardPage from './pages/desk/TournamentDeskBoardPage'
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
        {/* Public routes */}
        <Route path="/t/:tournamentId/draws" element={<PublicDrawsPage />} />
        <Route path="/t/:tournamentId/draws/:eventId/waterfall" element={<PublicWaterfallPage />} />
        <Route path="/t/:tournamentId/draws/:eventId/bracket/:divisionCode" element={<PublicBracketPage />} />
        <Route path="/t/:tournamentId/draws/:eventId/roundrobin" element={<PublicRoundRobinPage />} />
        <Route path="/t/:tournamentId/schedule" element={<PublicSchedulePage />} />
        {/* Staff desk */}
        <Route path="/desk/t/:tournamentId" element={<TournamentDeskPage />} />
        <Route path="/desk/t/:tournamentId/board" element={<TournamentDeskBoardPage />} />
      </Routes>
    </div>
  )
}

export default App

