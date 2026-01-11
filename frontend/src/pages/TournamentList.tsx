import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { listTournaments, getEvents, duplicateTournament, deleteTournament, Tournament } from '../api/client'
import { showToast } from '../utils/toast'
import { confirmDialog } from '../utils/confirm'
import { getSettings } from '../utils/settings'
import './TournamentList.css'

function TournamentList() {
  const [tournaments, setTournaments] = useState<Tournament[]>([])
  const [eventCounts, setEventCounts] = useState<Record<number, number>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [processing, setProcessing] = useState<Record<number, 'duplicate' | 'delete' | null>>({})
  const navigate = useNavigate()

  useEffect(() => {
    loadTournaments()
  }, [])
  
  // Get current theme for conditional rendering
  const currentTheme = getSettings().theme

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
    e.preventDefault()
    console.log('Duplicate clicked for tournament:', tournament.id)
    try {
      setProcessing(prev => ({ ...prev, [tournament.id]: 'duplicate' }))
      console.log('Calling duplicateTournament API...')
      const duplicated = await duplicateTournament(tournament.id)
      console.log('Duplicate successful:', duplicated)
      showToast(`Tournament "${duplicated.name}" created`, 'success')
      await loadTournaments()
    } catch (err) {
      console.error('Duplicate error:', err)
      showToast(err instanceof Error ? err.message : 'Failed to duplicate tournament', 'error')
    } finally {
      setProcessing(prev => ({ ...prev, [tournament.id]: null }))
    }
  }
  
  const handleDelete = async (tournament: Tournament, e: React.MouseEvent) => {
    e.stopPropagation()
    // Don't prevent default - let the button work normally
    console.log('Delete clicked for tournament:', tournament.id)
    
    const eventCount = eventCounts[tournament.id] || 0
    
    // Check if already processing
    if (processing[tournament.id]) {
      console.log('Already processing, ignoring click')
      return
    }
    
    console.log('Showing confirmation dialog...')
    // Show different warning if tournament has events
    const message = eventCount > 0
      ? `Are you sure you want to delete "${tournament.name}"?\n\nThis will permanently delete:\n- The tournament\n- ${eventCount} event(s) and all their data\n- All schedule data\n- All related information\n\nThis action cannot be undone!`
      : `Are you sure you want to delete "${tournament.name}"? This action cannot be undone.`
    
    const confirmed = await confirmDialog(message)
    console.log('Confirmation result:', confirmed)
    
    if (confirmed) {
      try {
        setProcessing(prev => ({ ...prev, [tournament.id]: 'delete' }))
        console.log('Calling deleteTournament API for tournament:', tournament.id)
        await deleteTournament(tournament.id)
        console.log('Delete successful')
        showToast('Tournament deleted successfully', 'success')
        await loadTournaments()
      } catch (err) {
        console.error('Delete error:', err)
        showToast(err instanceof Error ? err.message : 'Failed to delete tournament', 'error')
      } finally {
        setProcessing(prev => ({ ...prev, [tournament.id]: null }))
      }
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
          <button className="btn btn-secondary" onClick={handleSettingsClick}>
            Settings
          </button>
          <button className="btn btn-primary" onClick={handleCreateClick}>
            Create Tournament
          </button>
        </div>
      </div>

      {tournaments.length === 0 ? (
        <div className="card">
          <p>No tournaments found. Create your first tournament to get started.</p>
        </div>
      ) : (
        <div className="card">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Location</th>
                <th>Date Range</th>
                <th>Timezone</th>
                <th style={{ width: '150px' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {tournaments.map((tournament) => {
                const eventCount = eventCounts[tournament.id] || 0
                const canDelete = true  // Always allow deletion (backend will handle cascade)
                const isProcessing = processing[tournament.id]
                
                // Debug logging
                console.log('Rendering tournament:', tournament.id, tournament.name, { 
                  eventCount, 
                  canDelete, 
                  isProcessing,
                  buttonDisabled: !canDelete || !!isProcessing
                })
                
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
                    <td 
                      onClick={(e) => {
                        console.log('Actions cell clicked')
                        e.stopPropagation()
                      }}
                      style={{ position: 'relative', zIndex: 10 }}
                    >
                      <div style={{ display: 'flex', gap: '8px', position: 'relative', zIndex: 11 }}>
                        <button
                          type="button"
                          className="btn btn-primary"
                          style={{ fontSize: '12px', padding: '6px 12px', position: 'relative', zIndex: 12 }}
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
                          className="btn btn-secondary"
                          style={{ fontSize: '12px', padding: '6px 12px', position: 'relative', zIndex: 12 }}
                          onClick={(e) => {
                            console.log('Duplicate button clicked!', tournament.id)
                            e.stopPropagation()
                            handleDuplicate(tournament, e)
                          }}
                          disabled={!!isProcessing}
                          title="Duplicate tournament"
                        >
                          {isProcessing === 'duplicate' ? '...' : 'Duplicate'}
                        </button>
                        <button
                          type="button"
                          className="btn btn-danger"
                          style={{ 
                            fontSize: '12px', 
                            padding: '6px 12px', 
                            position: 'relative', 
                            zIndex: 12,
                            cursor: (!canDelete || !!isProcessing) ? 'not-allowed' : 'pointer',
                            opacity: (!canDelete || !!isProcessing) ? 0.6 : 1
                          }}
                          onClick={(e) => {
                            console.log('=== DELETE BUTTON CLICKED ===')
                            console.log('Tournament ID:', tournament.id)
                            console.log('Can Delete:', canDelete)
                            console.log('Is Processing:', isProcessing)
                            console.log('Event Count:', eventCount)
                            console.log('Button Disabled:', !canDelete || !!isProcessing)
                            e.stopPropagation()
                            if (!canDelete || isProcessing) {
                              console.log('Button is disabled, ignoring click')
                              return
                            }
                            console.log('Calling handleDelete...')
                            handleDelete(tournament, e)
                          }}
                          disabled={!!isProcessing}
                          title={eventCount > 0 ? `Delete tournament (will also delete ${eventCount} event${eventCount === 1 ? '' : 's'})` : 'Delete tournament'}
                        >
                          {isProcessing === 'delete' ? '...' : 'Delete'}
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default TournamentList

