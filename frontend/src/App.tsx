import { useEffect } from 'react'
import { Routes, Route, Navigate, Outlet, useLocation } from 'react-router-dom'
import TournamentList from './pages/TournamentList'
import CreateTournamentFromRwOs from './pages/CreateTournamentFromRwOs'
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
import PublicTeamPhotoPage from './pages/public/PublicTeamPhotoPage'
import PublicTournamentHubPage from './pages/public/PublicTournamentHubPage'
import PublicTournamentTeamPage from './pages/public/PublicTournamentTeamPage'
import TournamentDeskPage from './pages/desk/TournamentDeskPage'
import TournamentDeskBoardPage from './pages/desk/TournamentDeskBoardPage'
import TournamentDeskCheckinBoardPage from './pages/desk/TournamentDeskCheckinBoardPage'
import TournamentDeskDrawsDisplayPage from './pages/desk/TournamentDeskDrawsDisplayPage'
import TournamentDeskSharedScreenPage from './pages/desk/TournamentDeskSharedScreenPage'
import CourtAssignedPage from './pages/display/CourtAssignedPage'
import CourtBoardPage from './pages/display/CourtBoardPage'
import DynamicScreenPage from './pages/display/DynamicScreenPage'
import UpcomingMatchesPage from './pages/display/UpcomingMatchesPage'
import DrawQrBoardPage from './pages/drawQr/DrawQrBoardPage'
import TournamentHubQrPage from './pages/tournamentHub/TournamentHubQrPage'
import { getCurrentTheme, applyTheme } from './utils/settings'
import { getAuthToken, getAuthRole } from './api/client'
import LoginPage from './pages/LoginPage'
import PhotographerPage from './pages/PhotographerPage'
import PhotoPrintPage from './pages/photoPrint/PhotoPrintPage'

function RequireAuthLayout() {
  const location = useLocation()
  const token = getAuthToken()
  const role = getAuthRole()
  if (!token) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }
  const photographerPath = location.pathname.startsWith('/photography') || location.pathname.endsWith('/photo-print')
  if (role === 'photographer' && !photographerPath) {
    return <Navigate to="/photography" replace />
  }
  return <Outlet />
}

function App() {
  useEffect(() => {
    // Apply theme on mount
    const theme = getCurrentTheme()
    applyTheme(theme)
  }, [])

  return (
    <div className="App">
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        {/* Public routes */}
        <Route path="/t/:tournamentId/hub" element={<PublicTournamentHubPage />} />
        <Route path="/t/:tournamentId/hub/teams/:teamId" element={<PublicTournamentTeamPage />} />
        <Route path="/t/:tournamentId/draws" element={<PublicDrawsPage />} />
        <Route path="/t/:tournamentId/draws/:eventId/waterfall" element={<PublicWaterfallPage />} />
        <Route path="/t/:tournamentId/draws/:eventId/bracket/:divisionCode" element={<PublicBracketPage />} />
        <Route path="/t/:tournamentId/draws/:eventId/roundrobin" element={<PublicRoundRobinPage />} />
        <Route path="/t/:tournamentId/schedule" element={<PublicSchedulePage />} />
        <Route path="/p/photo/:token" element={<PublicTeamPhotoPage />} />

        <Route element={<RequireAuthLayout />}>
          <Route path="/" element={<TournamentList />} />
          <Route path="/tournaments" element={<TournamentList />} />
          <Route path="/tournaments/new" element={<CreateTournamentFromRwOs />} />
          <Route path="/tournaments/:id/import" element={<CreateTournamentFromRwOs />} />
          <Route path="/tournaments/:id/setup" element={<TournamentSetup />} />
          <Route path="/tournaments/:id/draw-builder" element={<DrawBuilder />} />
          <Route path="/tournaments/:id/draw-qr-board" element={<DrawQrBoardPage />} />
          <Route path="/tournaments/:id/tournament-qr" element={<TournamentHubQrPage />} />
          <Route path="/tournaments/:id/schedule-builder" element={<ScheduleBuilderPage />} />
          <Route path="/tournaments/:id/schedule" element={<SchedulePageGridV1 />} />
          <Route path="/tournaments/:id/schedule/matches" element={<MatchCardsRedirectToActive />} />
          <Route path="/tournaments/:id/schedule/versions/:versionId/matches" element={<MatchCardsPage />} />
          <Route path="/tournaments/:id/schedule/editor" element={<ScheduleEditorPage />} />
          <Route path="/events/:eventId/who-knows-who" element={<WhoKnowsWho />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/photography" element={<PhotographerPage />} />
          <Route path="/tournaments/:tournamentId/photo-print" element={<PhotoPrintPage />} />
          {/* Staff desk */}
          <Route path="/desk/t/:tournamentId" element={<TournamentDeskPage />} />
          <Route path="/desk/t/:tournamentId/board" element={<TournamentDeskBoardPage />} />
          <Route path="/desk/t/:tournamentId/checkin-board" element={<TournamentDeskCheckinBoardPage />} />
          <Route path="/desk/t/:tournamentId/draws-display" element={<TournamentDeskDrawsDisplayPage />} />
          <Route path="/desk/t/:tournamentId/shared-screen" element={<TournamentDeskSharedScreenPage />} />
          <Route path="/desk/t/:tournamentId/display/courts" element={<CourtBoardPage />} />
          <Route path="/desk/t/:tournamentId/display/court-assigned" element={<CourtAssignedPage />} />
          <Route path="/desk/t/:tournamentId/display/dynamic" element={<DynamicScreenPage />} />
          <Route path="/desk/t/:tournamentId/display/upcoming" element={<UpcomingMatchesPage />} />
        </Route>
      </Routes>
    </div>
  )
}

export default App

