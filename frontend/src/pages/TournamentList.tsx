import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  listTournaments,
  getEvents,
  duplicateTournament,
  deleteTournament,
  updateTournament,
  downloadTournamentPrintPacket,
  logoutAuth,
  clearAuthToken,
  Tournament,
} from '../api/client'
import { showToast } from '../utils/toast'
import { confirmDialog } from '../utils/confirm'
import { buildRenderedPrintPacketPdf } from '../utils/renderedPrintPacket'
import './TournamentList.css'

function TournamentList() {
  const [tournaments, setTournaments] = useState<Tournament[]>([])
  const [eventCounts, setEventCounts] = useState<Record<number, number>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [processing, setProcessing] = useState<Record<number, 'duplicate' | 'delete' | 'archive' | 'restore' | null>>({})
  const [printing, setPrinting] = useState<Record<string, boolean>>({})
  const [pastExpanded, setPastExpanded] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    loadTournaments()
  }, [])

  const loadTournaments = async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await listTournaments()
      setTournaments(data)

      // Load event counts for each tournament
      const counts: Record<number, number> = {}
      for (const tournament of data) {
        try {
          const events = await getEvents(tournament.id)
          counts[tournament.id] = events.length
        } catch {
          counts[tournament.id] = 0
        }
      }
      setEventCounts(counts)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load tournaments')
    } finally {
      setLoading(false)
    }
  }
  
  const handleDuplicate = async (tournament: Tournament, e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      setProcessing(prev => ({ ...prev, [tournament.id]: 'duplicate' }))
      const duplicated = await duplicateTournament(tournament.id)
      showToast(`Tournament "${duplicated.name}" created`, 'success')
      await loadTournaments()
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to duplicate tournament', 'error')
    } finally {
      setProcessing(prev => ({ ...prev, [tournament.id]: null }))
    }
  }
  
  const handleDelete = async (tournament: Tournament, e: React.MouseEvent) => {
    e.stopPropagation()
    const eventCount = eventCounts[tournament.id] || 0
    if (processing[tournament.id]) {
      return
    }

    const message = eventCount > 0
      ? `Are you sure you want to delete "${tournament.name}"?\n\nThis will permanently delete:\n- The tournament\n- ${eventCount} event(s) and all their data\n- All schedule data\n- All related information\n\nThis action cannot be undone!`
      : `Are you sure you want to delete "${tournament.name}"? This action cannot be undone.`

    const confirmed = await confirmDialog(message)

    if (confirmed) {
      try {
        setProcessing(prev => ({ ...prev, [tournament.id]: 'delete' }))
        await deleteTournament(tournament.id)
        showToast('Tournament deleted successfully', 'success')
        await loadTournaments()
      } catch (err) {
        showToast(err instanceof Error ? err.message : 'Failed to delete tournament', 'error')
      } finally {
        setProcessing(prev => ({ ...prev, [tournament.id]: null }))
      }
    }
  }

  const handleArchiveToggle = async (
    tournament: Tournament,
    toArchived: boolean,
    e: React.MouseEvent
  ) => {
    e.stopPropagation()
    const actionKey: 'archive' | 'restore' = toArchived ? 'archive' : 'restore'
    try {
      setProcessing(prev => ({ ...prev, [tournament.id]: actionKey }))
      const question = toArchived
        ? `Move "${tournament.name}" to Past Events?`
        : `Restore "${tournament.name}" to Active Events?`
      const confirmed = await confirmDialog(question)
      if (!confirmed) return
      await updateTournament(tournament.id, { is_archived: toArchived })
      showToast(
        toArchived
          ? `"${tournament.name}" moved to Past Events`
          : `"${tournament.name}" restored to Active Events`,
        'success'
      )
      await loadTournaments()
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to update event folder', 'error')
    } finally {
      setProcessing(prev => ({ ...prev, [tournament.id]: null }))
    }
  }

  const formatDateRange = (start: string, end: string) => {
    const startDate = new Date(start)
    const endDate = new Date(end)
    return `${startDate.toLocaleDateString()} - ${endDate.toLocaleDateString()}`
  }

  const handleRowClick = (id: number) => {
    navigate(`/tournaments/${id}/setup`)
  }

  const handleCreateClick = () => {
    navigate('/tournaments/new/setup')
  }

  const handleSettingsClick = () => {
    navigate('/settings')
  }

  const handleLogoutClick = async () => {
    try {
      await logoutAuth()
    } catch {
      // Ignore logout request failures; clear client token anyway.
    } finally {
      clearAuthToken()
      navigate('/login')
    }
  }

  const triggerBrowserDownload = (blob: Blob, filename: string) => {
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  const safeFileName = (name: string) => (name || 'tournament').replace(/[^a-z0-9_-]+/gi, '_')

  const handlePrintPacketDownload = async (
    tournament: Tournament,
    category: 'womens' | 'mixed',
    e: React.MouseEvent
  ) => {
    e.stopPropagation()
    e.preventDefault()
    const key = `${tournament.id}-${category}`
    try {
      setPrinting(prev => ({ ...prev, [key]: true }))
      let blob: Blob
      try {
        // Preferred path: capture the actual rendered public draw pages and combine.
        blob = await buildRenderedPrintPacketPdf(tournament.id, category)
      } catch {
        // Fallback path: server-generated packet if browser capture fails.
        blob = await downloadTournamentPrintPacket(tournament.id, category)
      }
      const filename = `${safeFileName(tournament.name)}_${category}_draw_packet.pdf`
      triggerBrowserDownload(blob, filename)
      showToast(`${category === 'womens' ? "Women's" : 'Mixed'} print packet downloaded`, 'success')
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to download print packet', 'error')
    } finally {
      setPrinting(prev => ({ ...prev, [key]: false }))
    }
  }

  const sortedTournaments = useMemo(() => {
    return [...tournaments].sort((a, b) => {
      const aDate = new Date(a.start_date).getTime()
      const bDate = new Date(b.start_date).getTime()
      return bDate - aDate
    })
  }, [tournaments])

  const activeTournaments = useMemo(
    () => sortedTournaments.filter(t => !t.is_archived),
    [sortedTournaments]
  )

  const archivedTournaments = useMemo(
    () => sortedTournaments.filter(t => t.is_archived),
    [sortedTournaments]
  )

  const renderTournamentTable = (rows: Tournament[], pastSection: boolean) => (
    <div className="card">
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Location</th>
            <th>Date Range</th>
            <th>Timezone</th>
            <th style={{ width: '460px' }}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((tournament) => {
            const eventCount = eventCounts[tournament.id] || 0
            const isProcessing = processing[tournament.id]
            return (
              <tr
                key={tournament.id}
                className="clickable"
                onClick={() => handleRowClick(tournament.id)}
              >
                <td>{tournament.name}</td>
                <td>{tournament.location}</td>
                <td>{formatDateRange(tournament.start_date, tournament.end_date)}</td>
                <td>{tournament.timezone}</td>
                <td onClick={(e) => e.stopPropagation()}>
                  <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                    <button
                      type="button"
                      className="btn btn-primary"
                      style={{ fontSize: '12px', padding: '6px 12px' }}
                      onClick={(e) => {
                        e.stopPropagation()
                        handleRowClick(tournament.id)
                      }}
                      disabled={!!isProcessing}
                      title="Edit tournament"
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      className="btn btn-primary"
                      style={{
                        fontSize: '12px',
                        padding: '6px 12px',
                        backgroundColor: '#00796b',
                        borderColor: '#00796b',
                      }}
                      onClick={(e) => {
                        e.stopPropagation()
                        navigate(`/desk/t/${tournament.id}`)
                      }}
                      disabled={!!isProcessing}
                      title="Open tournament desk"
                    >
                      Desk
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary"
                      style={{ fontSize: '12px', padding: '6px 12px' }}
                      onClick={(e) => handleDuplicate(tournament, e)}
                      disabled={!!isProcessing}
                      title="Duplicate tournament"
                    >
                      {isProcessing === 'duplicate' ? '...' : 'Duplicate'}
                    </button>
                    <button
                      type="button"
                      className={pastSection ? 'btn btn-primary' : 'btn btn-secondary'}
                      style={{ fontSize: '12px', padding: '6px 12px' }}
                      onClick={(e) => handleArchiveToggle(tournament, !pastSection, e)}
                      disabled={!!isProcessing}
                      title={pastSection ? 'Restore to active events' : 'Move to past events'}
                    >
                      {isProcessing === 'archive' || isProcessing === 'restore'
                        ? '...'
                        : pastSection
                          ? 'Restore'
                          : 'Move to Past'}
                    </button>
                    <button
                      type="button"
                      className="btn btn-danger"
                      style={{
                        fontSize: '12px',
                        padding: '6px 12px',
                        cursor: !!isProcessing ? 'not-allowed' : 'pointer',
                        opacity: !!isProcessing ? 0.6 : 1
                      }}
                      onClick={(e) => handleDelete(tournament, e)}
                      disabled={!!isProcessing}
                      title={eventCount > 0 ? `Delete tournament (will also delete ${eventCount} event${eventCount === 1 ? '' : 's'})` : 'Delete tournament'}
                    >
                      {isProcessing === 'delete' ? '...' : 'Delete'}
                    </button>
                    <div style={{ display: 'flex', gap: '8px', flexBasis: '100%' }}>
                      <button
                        type="button"
                        className="btn btn-secondary"
                        style={{ fontSize: '12px', padding: '6px 12px', whiteSpace: 'nowrap' }}
                        onClick={(e) => handlePrintPacketDownload(tournament, 'womens', e)}
                        disabled={!!isProcessing || !!printing[`${tournament.id}-womens`]}
                        title="Download Women's 32x24 print PDF"
                      >
                        {printing[`${tournament.id}-womens`] ? '...' : "PDF Women's"}
                      </button>
                      <button
                        type="button"
                        className="btn btn-secondary"
                        style={{ fontSize: '12px', padding: '6px 12px', whiteSpace: 'nowrap' }}
                        onClick={(e) => handlePrintPacketDownload(tournament, 'mixed', e)}
                        disabled={!!isProcessing || !!printing[`${tournament.id}-mixed`]}
                        title="Download Mixed 32x24 print PDF"
                      >
                        {printing[`${tournament.id}-mixed`] ? '...' : 'PDF Mixed'}
                      </button>
                    </div>
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )

  if (loading) {
    return <div className="container"><div className="loading">Loading tournaments...</div></div>
  }

  if (error) {
    return (
      <div className="container">
        <div className="error-message">Error: {error}</div>
        <button className="btn btn-primary" onClick={loadTournaments}>Retry</button>
      </div>
    )
  }

  return (
    <div className="container">
      <div className="page-header">
        <h1>Tournaments</h1>
        <div className="header-actions">
          <button className="btn btn-secondary" onClick={handleLogoutClick}>
            Log Out
          </button>
          <button className="btn btn-secondary" onClick={handleSettingsClick}>
            Settings
          </button>
          <button className="btn btn-primary" onClick={handleCreateClick}>
            Create Tournament
          </button>
        </div>
      </div>

      {activeTournaments.length === 0 && archivedTournaments.length === 0 ? (
        <div className="card">
          <p>No tournaments found. Create your first tournament to get started.</p>
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 16 }}>
          <div>
            <h2 style={{ margin: '0 0 8px', fontSize: 18 }}>Active Events</h2>
            {activeTournaments.length === 0 ? (
              <div className="card">
                <p>No active events. Use “Restore” in Past Events to bring one back.</p>
              </div>
            ) : (
              renderTournamentTable(activeTournaments, false)
            )}
          </div>

          <div className="card" style={{ padding: 12 }}>
            <button
              type="button"
              className="btn btn-secondary"
              style={{ fontSize: 13, padding: '6px 12px' }}
              onClick={() => setPastExpanded(prev => !prev)}
            >
              {pastExpanded ? '▾' : '▸'} Past Events Folder ({archivedTournaments.length})
            </button>
            {pastExpanded && (
              <div style={{ marginTop: 10 }}>
                {archivedTournaments.length === 0 ? (
                  <div style={{ color: '#666', fontSize: 13 }}>
                    No past events yet. Use “Move to Past” on any active event.
                  </div>
                ) : (
                  renderTournamentTable(archivedTournaments, true)
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default TournamentList

