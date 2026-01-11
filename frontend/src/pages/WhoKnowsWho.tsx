import { useState, useEffect, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { showToast } from '../utils/toast'
import { confirmDialog } from '../utils/confirm'
import './WhoKnowsWho.css'

// ============================================================================
// API Helper
// ============================================================================

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';

async function apiFetch<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  })
  
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(error.detail || `HTTP ${response.status}`)
  }
  
  return response.json()
}

// ============================================================================
// Types
// ============================================================================

interface Team {
  id: number
  event_id: number
  name: string
  seed: number | null
  rating: number | null
  registration_timestamp: string | null
  created_at: string
  wf_group_index: number | null
}

interface AvoidEdge {
  id: number
  event_id: number
  team_id_a: number
  team_id_b: number
  reason: string | null
  created_at: string
}

interface ConflictedPair {
  team_a_id: number
  team_a_name: string
  team_b_id: number
  team_b_name: string
  group_index: number
  reason: string | null
}

interface ConflictLens {
  event_id: number
  event_name: string
  graph_summary: {
    team_count: number
    avoid_edges_count: number
    connected_components_count: number
    largest_component_size: number
    top_degree_teams: Array<{
      team_id: number
      team_name: string
      degree: number
    }>
  }
  grouping_summary: {
    groups_count: number
    group_sizes: number[]
    total_internal_conflicts: number
    conflicts_by_group: Record<number, number>
  } | null
  unavoidable_conflicts: ConflictedPair[]
  separation_effectiveness: {
    separated_edges: number
    separation_rate: number
  } | null
}

interface BulkResponse {
  dry_run: boolean
  created_count?: number
  would_create_count?: number
  skipped_duplicates_count?: number
  would_skip_duplicates_count?: number
  rejected_count: number
  rejected_items: Array<{ input: any; error: string }>
  created_edges_sample?: Array<any>
  would_create_edges?: Array<{ team_id_a: number; team_id_b: number; reason: string | null }>
}

// ============================================================================
// Main Component
// ============================================================================

export default function WhoKnowsWho() {
  const { eventId } = useParams<{ eventId: string }>()
  const navigate = useNavigate()
  
  const [teams, setTeams] = useState<Team[]>([])
  const [avoidEdges, setAvoidEdges] = useState<AvoidEdge[]>([])
  const [conflictLens, setConflictLens] = useState<ConflictLens | null>(null)
  const [loading, setLoading] = useState(true)
  const [recomputeLoading, setRecomputeLoading] = useState(false)
  
  // UI state
  const [selectedTeamIds, setSelectedTeamIds] = useState<Set<number>>(new Set())
  const [searchQuery, setSearchQuery] = useState('')
  const [activeTab, setActiveTab] = useState<'pair' | 'group'>('pair')
  const [edgeFilter, setEdgeFilter] = useState({ team: '', reason: '' })
  
  // Form state
  const [pairForm, setPairForm] = useState({ teamA: '', teamB: '', reason: '' })
  const [groupForm, setGroupForm] = useState({ code: '', reason: '' })
  const [bulkPaste, setBulkPaste] = useState('')
  
  // Preview state
  const [previewResponse, setPreviewResponse] = useState<BulkResponse | null>(null)
  const [showPreview, setShowPreview] = useState(false)
  
  // Team map for lookups
  const teamMap = useMemo(() => {
    const map = new Map<number, Team>()
    teams.forEach(t => map.set(t.id, t))
    return map
  }, [teams])
  
  // Load data
  useEffect(() => {
    loadData()
  }, [eventId])
  
  async function loadData() {
    if (!eventId) return
    
    setLoading(true)
    try {
      // Parallel fetch
      const [teamsRes, edgesRes, lensRes] = await Promise.all([
        apiFetch<Team[]>(`${API_BASE_URL}/events/${eventId}/teams?include_grouping=true`),
        apiFetch<AvoidEdge[]>(`${API_BASE_URL}/events/${eventId}/avoid-edges`),
        apiFetch<ConflictLens>(`${API_BASE_URL}/events/${eventId}/waterfall/conflicts`),
      ])
      
      setTeams(teamsRes)
      setAvoidEdges(edgesRes)
      setConflictLens(lensRes)
    } catch (error: any) {
      showToast('Failed to load data: ' + error.message, 'error')
    } finally {
      setLoading(false)
    }
  }
  
  // Filter teams by search
  const filteredTeams = useMemo(() => {
    if (!searchQuery) return teams
    const q = searchQuery.toLowerCase()
    return teams.filter(t => t.name.toLowerCase().includes(q))
  }, [teams, searchQuery])
  
  // Filter edges
  const filteredEdges = useMemo(() => {
    return avoidEdges.filter(edge => {
      const teamA = teamMap.get(edge.team_id_a)
      const teamB = teamMap.get(edge.team_id_b)
      
      if (edgeFilter.team) {
        const teamQuery = edgeFilter.team.toLowerCase()
        if (!teamA?.name.toLowerCase().includes(teamQuery) && 
            !teamB?.name.toLowerCase().includes(teamQuery)) {
          return false
        }
      }
      
      if (edgeFilter.reason) {
        const reasonQuery = edgeFilter.reason.toLowerCase()
        if (!edge.reason?.toLowerCase().includes(reasonQuery)) {
          return false
        }
      }
      
      return true
    })
  }, [avoidEdges, edgeFilter, teamMap])
  
  // ============================================================================
  // Handlers - Pair Add
  // ============================================================================
  
  async function handlePairPreview() {
    if (!eventId || !pairForm.teamA || !pairForm.teamB) {
      showToast('Select both teams', 'error')
      return
    }
    
    try {
      const response = await apiFetch<BulkResponse>(
        `${API_BASE_URL}/events/${eventId}/avoid-edges/bulk?dry_run=true`,
        {
          method: 'POST',
          body: JSON.stringify({
            pairs: [{
              team_a_id: parseInt(pairForm.teamA),
              team_b_id: parseInt(pairForm.teamB),
              reason: pairForm.reason || null
            }]
          })
        }
      )
      
      setPreviewResponse(response)
      setShowPreview(true)
    } catch (error: any) {
      showToast('Preview failed: ' + error.message, 'error')
    }
  }
  
  async function handlePairConfirm() {
    if (!eventId || !pairForm.teamA || !pairForm.teamB) return
    
    try {
      const response = await apiFetch<BulkResponse>(
        `${API_BASE_URL}/events/${eventId}/avoid-edges/bulk?dry_run=false`,
        {
          method: 'POST',
          body: JSON.stringify({
            pairs: [{
              team_a_id: parseInt(pairForm.teamA),
              team_b_id: parseInt(pairForm.teamB),
              reason: pairForm.reason || null
            }]
          })
        }
      )
      
      showToast(`Created ${response.created_count} edge(s)`, 'success')
      setPairForm({ teamA: '', teamB: '', reason: '' })
      setShowPreview(false)
      setPreviewResponse(null)
      await loadData()
    } catch (error: any) {
      showToast('Failed to add pair: ' + error.message, 'error')
    }
  }
  
  // ============================================================================
  // Handlers - Group Add
  // ============================================================================
  
  async function handleGroupPreview() {
    if (!eventId || !groupForm.code || selectedTeamIds.size < 2) {
      showToast('Enter code and select at least 2 teams', 'error')
      return
    }
    
    try {
      const response = await apiFetch<BulkResponse>(
        `${API_BASE_URL}/events/${eventId}/avoid-edges/bulk?dry_run=true`,
        {
          method: 'POST',
          body: JSON.stringify({
            link_groups: [{
              code: groupForm.code,
              team_ids: Array.from(selectedTeamIds),
              reason: groupForm.reason || null
            }]
          })
        }
      )
      
      setPreviewResponse(response)
      setShowPreview(true)
    } catch (error: any) {
      showToast('Preview failed: ' + error.message, 'error')
    }
  }
  
  async function handleGroupConfirm() {
    if (!eventId || !groupForm.code || selectedTeamIds.size < 2) return
    
    try {
      const response = await apiFetch<BulkResponse>(
        `${API_BASE_URL}/events/${eventId}/avoid-edges/bulk?dry_run=false`,
        {
          method: 'POST',
          body: JSON.stringify({
            link_groups: [{
              code: groupForm.code,
              team_ids: Array.from(selectedTeamIds),
              reason: groupForm.reason || null
            }]
          })
        }
      )
      
      showToast(`Created ${response.created_count} edge(s) for group "${groupForm.code}"`, 'success')
      setGroupForm({ code: '', reason: '' })
      setSelectedTeamIds(new Set())
      setShowPreview(false)
      setPreviewResponse(null)
      await loadData()
    } catch (error: any) {
      showToast('Failed to add group: ' + error.message, 'error')
    }
  }
  
  // ============================================================================
  // Handlers - Bulk Paste
  // ============================================================================
  
  function parseBulkPaste(text: string): Array<{ team_a_id: number; team_b_id: number; reason: string | null }> | null {
    const lines = text.trim().split('\n').filter(l => l.trim())
    const pairs: Array<{ team_a_id: number; team_b_id: number; reason: string | null }> = []
    
    for (const line of lines) {
      // Try CSV: id,id,reason or name|name|reason
      const csvMatch = line.split(',')
      const pipeMatch = line.split('|')
      
      let teamAStr = '', teamBStr = '', reason = null
      
      if (csvMatch.length >= 2) {
        teamAStr = csvMatch[0].trim()
        teamBStr = csvMatch[1].trim()
        reason = csvMatch[2]?.trim() || null
      } else if (pipeMatch.length >= 2) {
        teamAStr = pipeMatch[0].trim()
        teamBStr = pipeMatch[1].trim()
        reason = pipeMatch[2]?.trim() || null
      } else {
        return null // Invalid format
      }
      
      // Try to resolve as ID or name
      const teamA = parseInt(teamAStr) ? 
        teamMap.get(parseInt(teamAStr)) : 
        teams.find(t => t.name.toLowerCase() === teamAStr.toLowerCase())
      
      const teamB = parseInt(teamBStr) ? 
        teamMap.get(parseInt(teamBStr)) : 
        teams.find(t => t.name.toLowerCase() === teamBStr.toLowerCase())
      
      if (!teamA || !teamB) {
        return null // Can't resolve
      }
      
      pairs.push({ team_a_id: teamA.id, team_b_id: teamB.id, reason })
    }
    
    return pairs
  }
  
  async function handleBulkPreview() {
    if (!eventId || !bulkPaste.trim()) {
      showToast('Enter bulk data', 'error')
      return
    }
    
    const pairs = parseBulkPaste(bulkPaste)
    if (!pairs) {
      showToast('Invalid format. Use: teamA,teamB,reason or teamA|teamB|reason per line', 'error')
      return
    }
    
    try {
      const response = await apiFetch<BulkResponse>(
        `${API_BASE_URL}/events/${eventId}/avoid-edges/bulk?dry_run=true`,
        {
          method: 'POST',
          body: JSON.stringify({ pairs })
        }
      )
      
      setPreviewResponse(response)
      setShowPreview(true)
    } catch (error: any) {
      showToast('Preview failed: ' + error.message, 'error')
    }
  }
  
  async function handleBulkConfirm() {
    if (!eventId || !bulkPaste.trim()) return
    
    const pairs = parseBulkPaste(bulkPaste)
    if (!pairs) return
    
    try {
      const response = await apiFetch<BulkResponse>(
        `${API_BASE_URL}/events/${eventId}/avoid-edges/bulk?dry_run=false`,
        {
          method: 'POST',
          body: JSON.stringify({ pairs })
        }
      )
      
      showToast(`Created ${response.created_count} edge(s), skipped ${response.skipped_duplicates_count} duplicate(s)`, 'success')
      setBulkPaste('')
      setShowPreview(false)
      setPreviewResponse(null)
      await loadData()
    } catch (error: any) {
      showToast('Failed bulk operation: ' + error.message, 'error')
    }
  }
  
  // ============================================================================
  // Handlers - Delete Edge
  // ============================================================================
  
  async function handleDeleteEdge(edgeId: number) {
    const confirmed = await confirmDialog('Delete this avoid edge?')
    if (!confirmed) return
    
    try {
      await apiFetch<void>(
        `${API_BASE_URL}/events/${eventId}/avoid-edges/${edgeId}`,
        { method: 'DELETE' }
      )
      showToast('Edge deleted', 'success')
      await loadData()
    } catch (error: any) {
      showToast('Delete failed: ' + error.message, 'error')
    }
  }
  
  // ============================================================================
  // Handlers - Recompute Groups
  // ============================================================================
  
  async function handleRecomputeGroups() {
    if (!eventId) return
    
    const confirmed = await confirmDialog('Recompute Waterfall groups? This will reassign all teams.')
    if (!confirmed) return
    
    setRecomputeLoading(true)
    try {
      const response = await apiFetch<{ groups_count: number; total_internal_conflicts: number }>(
        `${API_BASE_URL}/events/${eventId}/waterfall/assign-groups?clear_existing=true`,
        { method: 'POST' }
      )
      
      showToast(`Groups assigned: ${response.groups_count} groups with ${response.total_internal_conflicts} unavoidable conflicts`, 'success')
      await loadData()
    } catch (error: any) {
      showToast('Recompute failed: ' + error.message, 'error')
    } finally {
      setRecomputeLoading(false)
    }
  }
  
  // ============================================================================
  // Render
  // ============================================================================
  
  if (loading) {
    return <div className="who-knows-who-page"><div className="loading">Loading...</div></div>
  }
  
  return (
    <div className="who-knows-who-page">
      {/* Header */}
      <header className="page-header">
        <button onClick={() => navigate(-1)} className="back-button">← Back</button>
        <h1>Who Knows Who - Conflict Management</h1>
        <button 
          onClick={handleRecomputeGroups} 
          disabled={recomputeLoading}
          className="recompute-button"
        >
          {recomputeLoading ? 'Computing...' : '🔄 Assign Waterfall Groups'}
        </button>
      </header>
      
      {/* Conflict Summary Banner */}
      {conflictLens && (
        <div className="conflict-banner">
          <div className="banner-stat">
            <strong>Teams:</strong> {conflictLens.graph_summary.team_count}
          </div>
          <div className="banner-stat">
            <strong>Avoid Edges:</strong> {conflictLens.graph_summary.avoid_edges_count}
          </div>
          {conflictLens.separation_effectiveness && (
            <>
              <div className="banner-stat success">
                <strong>Separated:</strong> {conflictLens.separation_effectiveness.separated_edges} ({(conflictLens.separation_effectiveness.separation_rate * 100).toFixed(1)}%)
              </div>
              <div className="banner-stat warning">
                <strong>Unavoidable:</strong> {conflictLens.grouping_summary?.total_internal_conflicts || 0}
              </div>
            </>
          )}
        </div>
      )}
      
      <div className="content-grid">
        {/* Left Column - Teams Panel */}
        <div className="panel teams-panel">
          <h2>Teams ({teams.length})</h2>
          
          <input 
            type="text"
            placeholder="Search teams..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="search-input"
          />
          
          <div className="teams-list">
            {filteredTeams.map(team => (
              <label key={team.id} className="team-item">
                <input 
                  type="checkbox"
                  checked={selectedTeamIds.has(team.id)}
                  onChange={e => {
                    const newSet = new Set(selectedTeamIds)
                    if (e.target.checked) {
                      newSet.add(team.id)
                    } else {
                      newSet.delete(team.id)
                    }
                    setSelectedTeamIds(newSet)
                  }}
                />
                <span className="team-name">{team.name}</span>
                {team.seed !== null && <span className="badge seed">Seed {team.seed}</span>}
                {team.wf_group_index !== null && <span className="badge group">Group {team.wf_group_index}</span>}
              </label>
            ))}
          </div>
          
          {selectedTeamIds.size > 0 && (
            <div className="selection-info">
              {selectedTeamIds.size} team(s) selected
              <button onClick={() => setSelectedTeamIds(new Set())} className="clear-btn">Clear</button>
            </div>
          )}
        </div>
        
        {/* Right Column */}
        <div className="right-column">
          {/* Add Links Panel */}
          <div className="panel add-links-panel">
            <h2>Add Avoid Edges</h2>
            
            <div className="tabs">
              <button 
                className={activeTab === 'pair' ? 'active' : ''}
                onClick={() => setActiveTab('pair')}
              >
                Pair Add
              </button>
              <button 
                className={activeTab === 'group' ? 'active' : ''}
                onClick={() => setActiveTab('group')}
              >
                Group Add
              </button>
            </div>
            
            {activeTab === 'pair' && (
              <div className="tab-content">
                <div className="form-group">
                  <label>Team A</label>
                  <select value={pairForm.teamA} onChange={e => setPairForm({...pairForm, teamA: e.target.value})}>
                    <option value="">Select team...</option>
                    {teams.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
                  </select>
                </div>
                
                <div className="form-group">
                  <label>Team B</label>
                  <select value={pairForm.teamB} onChange={e => setPairForm({...pairForm, teamB: e.target.value})}>
                    <option value="">Select team...</option>
                    {teams.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}
                  </select>
                </div>
                
                <div className="form-group">
                  <label>Reason (optional)</label>
                  <input 
                    type="text"
                    value={pairForm.reason}
                    onChange={e => setPairForm({...pairForm, reason: e.target.value})}
                    placeholder="e.g., same club"
                  />
                </div>
                
                <button onClick={handlePairPreview} className="preview-btn">Preview</button>
              </div>
            )}
            
            {activeTab === 'group' && (
              <div className="tab-content">
                <div className="form-group">
                  <label>Group Code</label>
                  <input 
                    type="text"
                    value={groupForm.code}
                    onChange={e => setGroupForm({...groupForm, code: e.target.value})}
                    placeholder="e.g., ESPLANADE"
                  />
                </div>
                
                <div className="form-group">
                  <label>Reason (optional)</label>
                  <input 
                    type="text"
                    value={groupForm.reason}
                    onChange={e => setGroupForm({...groupForm, reason: e.target.value})}
                    placeholder="e.g., same club"
                  />
                </div>
                
                <div className="info-box">
                  Select teams from the left panel. Group creates avoid edges between all pairs within the group.
                  <br />
                  <strong>Selected: {selectedTeamIds.size} teams</strong>
                  {selectedTeamIds.size >= 2 && (
                    <span> → Will create {selectedTeamIds.size * (selectedTeamIds.size - 1) / 2} edges</span>
                  )}
                </div>
                
                <button onClick={handleGroupPreview} className="preview-btn">Preview Group</button>
              </div>
            )}
          </div>
          
          {/* Bulk Paste Panel */}
          <div className="panel bulk-paste-panel">
            <h2>Bulk Paste</h2>
            <p className="help-text">
              Enter one pair per line. Formats: <code>teamA_id,teamB_id,reason</code> or <code>teamA_name|teamB_name|reason</code>
            </p>
            <textarea 
              value={bulkPaste}
              onChange={e => setBulkPaste(e.target.value)}
              placeholder="1,2,same club&#10;Team A|Team B|same facility"
              rows={6}
            />
            <button onClick={handleBulkPreview} className="preview-btn">Preview Bulk</button>
          </div>
          
          {/* Preview Modal */}
          {showPreview && previewResponse && (
            <div className="preview-modal">
              <div className="preview-content">
                <h3>Preview Results</h3>
                
                <div className="preview-stats">
                  <div className="stat">
                    <strong>Will Create:</strong> {previewResponse.would_create_count || 0}
                  </div>
                  <div className="stat">
                    <strong>Will Skip (Duplicates):</strong> {previewResponse.would_skip_duplicates_count || 0}
                  </div>
                  <div className="stat">
                    <strong>Rejected:</strong> {previewResponse.rejected_count}
                  </div>
                </div>
                
                {previewResponse.rejected_count > 0 && (
                  <div className="rejected-items">
                    <h4>Rejected Items:</h4>
                    {previewResponse.rejected_items.map((item, idx) => (
                      <div key={idx} className="rejected-item">
                        {JSON.stringify(item.input)} - <strong>{item.error}</strong>
                      </div>
                    ))}
                  </div>
                )}
                
                {previewResponse.would_create_edges && previewResponse.would_create_edges.length > 0 && (
                  <div className="preview-edges">
                    <h4>Edges to Create:</h4>
                    <table>
                      <thead>
                        <tr>
                          <th>Team A</th>
                          <th>Team B</th>
                          <th>Reason</th>
                        </tr>
                      </thead>
                      <tbody>
                        {previewResponse.would_create_edges.slice(0, 20).map((edge, idx) => (
                          <tr key={idx}>
                            <td>{teamMap.get(edge.team_id_a)?.name || edge.team_id_a}</td>
                            <td>{teamMap.get(edge.team_id_b)?.name || edge.team_id_b}</td>
                            <td>{edge.reason || '-'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {previewResponse.would_create_edges.length > 20 && (
                      <p className="more-info">...and {previewResponse.would_create_edges.length - 20} more</p>
                    )}
                  </div>
                )}
                
                <div className="preview-actions">
                  <button onClick={() => setShowPreview(false)} className="cancel-btn">Cancel</button>
                  {(previewResponse.would_create_count || 0) > 0 && (
                    <button 
                      onClick={() => {
                        if (activeTab === 'pair') handlePairConfirm()
                        else if (activeTab === 'group') handleGroupConfirm()
                        else handleBulkConfirm()
                      }} 
                      className="confirm-btn"
                    >
                      Confirm & Create
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
      
      {/* Bottom Row - Existing Edges and Grouping Results */}
      <div className="bottom-row">
        {/* Existing Edges Table */}
        <div className="panel edges-table-panel">
          <h2>Existing Avoid Edges ({avoidEdges.length})</h2>
          
          <div className="filters">
            <input 
              type="text"
              placeholder="Filter by team..."
              value={edgeFilter.team}
              onChange={e => setEdgeFilter({...edgeFilter, team: e.target.value})}
            />
            <input 
              type="text"
              placeholder="Filter by reason..."
              value={edgeFilter.reason}
              onChange={e => setEdgeFilter({...edgeFilter, reason: e.target.value})}
            />
          </div>
          
          <div className="edges-table-container">
            <table className="edges-table">
              <thead>
                <tr>
                  <th>Team A</th>
                  <th>Team B</th>
                  <th>Reason</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredEdges.map(edge => (
                  <tr key={edge.id}>
                    <td>{teamMap.get(edge.team_id_a)?.name || `ID ${edge.team_id_a}`}</td>
                    <td>{teamMap.get(edge.team_id_b)?.name || `ID ${edge.team_id_b}`}</td>
                    <td>{edge.reason || '-'}</td>
                    <td>
                      <button onClick={() => handleDeleteEdge(edge.id)} className="delete-btn">Delete</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        
        {/* Grouping Results Panel */}
        {conflictLens?.grouping_summary && (
          <div className="panel grouping-results-panel">
            <h2>Grouping Results</h2>
            
            <div className="grouping-stats">
              <div className="stat">
                <strong>Groups:</strong> {conflictLens.grouping_summary.groups_count}
              </div>
              <div className="stat">
                <strong>Sizes:</strong> [{conflictLens.grouping_summary.group_sizes.join(', ')}]
              </div>
              <div className="stat">
                <strong>Internal Conflicts:</strong> {conflictLens.grouping_summary.total_internal_conflicts}
              </div>
              {conflictLens.separation_effectiveness && (
                <div className="stat">
                  <strong>Separation Rate:</strong> {(conflictLens.separation_effectiveness.separation_rate * 100).toFixed(1)}%
                </div>
              )}
            </div>
            
            {conflictLens.unavoidable_conflicts.length > 0 && (
              <details className="unavoidable-conflicts">
                <summary>
                  Unavoidable Conflicts ({conflictLens.unavoidable_conflicts.length})
                </summary>
                <table>
                  <thead>
                    <tr>
                      <th>Team A</th>
                      <th>Team B</th>
                      <th>Group</th>
                      <th>Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {conflictLens.unavoidable_conflicts.map((conflict, idx) => (
                      <tr key={idx}>
                        <td>{conflict.team_a_name}</td>
                        <td>{conflict.team_b_name}</td>
                        <td>Group {conflict.group_index}</td>
                        <td>{conflict.reason || '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

