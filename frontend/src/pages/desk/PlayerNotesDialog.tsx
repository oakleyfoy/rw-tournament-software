import { useState } from 'react'

export type StaffNote = {
  id: number
  playerId: number
  playerName?: string
  body: string
  createdAt: string
  createdByName: string | null
  updatedAt?: string | null
  updatedByName?: string | null
}

export type NotePlayer = {
  id: number
  name: string
}

export type TeamLevelNote = {
  label: string
  body: string
}

export function notesForPlayers(notes: StaffNote[], playerIds: number[]): StaffNote[] {
  const ids = new Set(playerIds)
  return notes.filter((note) => ids.has(note.playerId))
}

export default function PlayerNotesDialog({
  players,
  notes,
  teamNotes = [],
  canAdd = false,
  canManage = false,
  onAdd,
  onEdit,
  onDelete,
  onClose,
}: {
  players: NotePlayer[]
  notes: StaffNote[]
  teamNotes?: TeamLevelNote[]
  canAdd?: boolean
  canManage?: boolean
  onAdd?: (playerIds: number[], body: string) => Promise<void>
  onEdit?: (noteId: number, body: string) => Promise<void>
  onDelete?: (noteId: number) => Promise<void>
  onClose: () => void
}) {
  const [body, setBody] = useState('')
  const [target, setTarget] = useState<'0' | '1' | 'both'>('0')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editingBody, setEditingBody] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const ordered = [...notes].sort((a, b) => (b.createdAt || '').localeCompare(a.createdAt || ''))
  const saveNew = async () => {
    const text = body.trim()
    if (!text) {
      setNotice('Enter a note.')
      return
    }
    const ids = target === 'both'
      ? players.map((player) => player.id)
      : [players[Number(target)]?.id].filter((id): id is number => id != null)
    if (!onAdd || ids.length === 0) return
    setBusy(true)
    setNotice('')
    try {
      await onAdd(ids, text)
      setBody('')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Could not save the note')
    } finally {
      setBusy(false)
    }
  }
  const saveEdit = async () => {
    if (editingId == null || !onEdit) return
    const text = editingBody.trim()
    if (!text) {
      setNotice('Enter a note.')
      return
    }
    setBusy(true)
    setNotice('')
    try {
      await onEdit(editingId, text)
      setEditingId(null)
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Could not update the note')
    } finally {
      setBusy(false)
    }
  }
  const remove = async (noteId: number) => {
    if (!onDelete) return
    if (!window.confirm('Delete this note?')) return
    setBusy(true)
    setNotice('')
    try {
      await onDelete(noteId)
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Could not delete the note')
    } finally {
      setBusy(false)
    }
  }
  return (
    <div role="presentation" onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1200, padding: 16 }}>
      <div role="dialog" aria-label="Player notes" onClick={(event) => event.stopPropagation()} style={{ width: 460, maxWidth: '100%', maxHeight: '80vh', overflow: 'auto', background: '#fff', borderRadius: 12, padding: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ fontSize: 16, fontWeight: 800 }}>Player notes</div>
        {players.map((player) => (
          <div key={player.id}>
            <div style={{ fontWeight: 800 }}>{player.name}</div>
            {ordered.filter((note) => note.playerId === player.id).map((note) => (
              <div key={note.id} style={{ fontSize: 13, margin: '4px 0 8px' }}>
                {editingId === note.id ? (
                  <textarea value={editingBody} onChange={(event) => setEditingBody(event.target.value)} rows={3} style={{ width: '100%', boxSizing: 'border-box' }} />
                ) : (
                  <div>{note.body}</div>
                )}
                <div style={{ color: '#607d8b' }}>
                  {new Date(note.createdAt).toLocaleString()}
                  {note.createdByName ? ` · ${note.createdByName}` : ''}
                  {note.updatedAt ? ` · edited ${new Date(note.updatedAt).toLocaleString()}${note.updatedByName ? ` by ${note.updatedByName}` : ''}` : ''}
                </div>
                {canManage && (
                  <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                    {editingId === note.id ? (
                      <button type="button" onClick={() => { void saveEdit() }} disabled={busy}>Save</button>
                    ) : (
                      <button type="button" onClick={() => { setEditingId(note.id); setEditingBody(note.body) }}>Edit</button>
                    )}
                    <button type="button" onClick={() => { void remove(note.id) }} disabled={busy}>Delete</button>
                  </div>
                )}
              </div>
            ))}
            {ordered.every((note) => note.playerId !== player.id) && <div style={{ color: '#90a4ae', fontSize: 13, marginBottom: 8 }}>No notes</div>}
          </div>
        ))}
        {teamNotes.filter((note) => note.body.trim()).map((note) => (
          <div key={note.label} style={{ fontSize: 13, background: '#fafafa', borderRadius: 8, padding: 8 }}>
            <div style={{ fontWeight: 800 }}>{note.label}</div>
            <div>{note.body}</div>
          </div>
        ))}
        {canAdd && (
          <>
            <textarea value={body} onChange={(event) => setBody(event.target.value)} rows={3} placeholder="Add a note" style={{ width: '100%', boxSizing: 'border-box', fontSize: 14, padding: 8 }} />
            <div style={{ display: 'flex', gap: 8, fontSize: 13, flexWrap: 'wrap' }}>
              {players.slice(0, 2).map((player, index) => (
                <label key={player.id}><input type="radio" name="note-target" checked={target === String(index)} onChange={() => setTarget(String(index) as '0' | '1')} /> {player.name.split(' ')[0]}</label>
              ))}
              {players.length > 1 && <label><input type="radio" name="note-target" checked={target === 'both'} onChange={() => setTarget('both')} /> Both players</label>}
            </div>
          </>
        )}
        {notice && <div style={{ color: '#c62828', fontSize: 13 }}>{notice}</div>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button type="button" onClick={onClose} disabled={busy}>Close</button>
          {canAdd && <button type="button" onClick={() => { void saveNew() }} disabled={busy}>{busy ? 'Saving…' : 'Save Note'}</button>}
        </div>
      </div>
    </div>
  )
}
