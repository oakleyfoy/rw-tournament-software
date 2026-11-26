import { useMemo, useState } from 'react'
import type { DeskMatchItem, SnapshotSlot } from '../../api/client'
import DesignatedCourtSheet from './DesignatedCourtSheet'
import PlayerNotesDialog from './PlayerNotesDialog'
import { buildDaySchedule, listScheduleDays } from './courtSheet'

const DAYS = ['2026-12-04', '2026-12-05', '2026-12-06']
const TIMES = ['09:00:00', '10:00:00', '11:00:00']

function buildSample(): { slots: SnapshotSlot[]; matches: DeskMatchItem[] } {
  const slots: SnapshotSlot[] = []
  const matches: DeskMatchItem[] = []
  let id = 1
  for (const day of DAYS) {
    for (const time of TIMES) {
      for (let court = 1; court <= 24; court += 1) {
        const inactive = (court === 7 && time === '09:00:00') || (court === 8 && time === '11:00:00')
        const empty = (court === 5 && time !== '11:00:00') || (court === 7 && time === '09:00:00')
        const status = day === DAYS[0] && time === '09:00:00' && court === 3
          ? 'IN_PROGRESS'
          : day === DAYS[0] && time === '09:00:00' && court < 3
            ? 'FINAL'
            : 'SCHEDULED'
        slots.push({
          slot_id: id,
          day_date: day,
          start_time: time,
          end_time: time === '09:00:00' ? '10:00:00' : time === '10:00:00' ? '11:00:00' : '12:00:00',
          court_number: court,
          court_label: String(court),
          block_minutes: 60,
          is_active: !inactive,
          assigned_match_id: empty ? null : id,
        })
        matches.push({
          match_id: id,
          match_number: 7000 + id,
          match_code: court % 2 === 0 ? 'WA_WF_R1' : 'MX_WF_R1',
          stage: 'WF',
          event_id: 1,
          event_name: 'Sample',
          division_name: null,
          day_index: DAYS.indexOf(day),
          day_label: day,
          scheduled_time: time.slice(0, 5),
          sort_time: time.slice(0, 5),
          court_name: `Court ${court}`,
          court_assignment_mode: 'PREASSIGNED',
          status,
          team1_id: court === 4 ? 4242 : status === 'SCHEDULED' && court === 6 ? null : id * 10,
          team1_display: status === 'IN_PROGRESS' ? 'Carol Smith / Olivia Jones' : court === 4 ? 'Alex Bose / Jennifer Myers' : status === 'SCHEDULED' && court === 6 ? 'WINNER:WA_WF_R1_M1' : `Alex ${court}`,
          team2_id: id * 10 + 1,
          team2_display: status === 'IN_PROGRESS' ? 'Jennifer Lee / Helen Park' : `Blake ${court}`,
          score_display: status === 'FINAL' ? '8-5' : null,
          source_match_a_id: court === 6 ? 1 : null,
          source_match_b_id: null,
          created_at: null,
          started_at: status === 'IN_PROGRESS' ? '2026-12-04T15:00:00Z' : null,
          completed_at: status === 'FINAL' ? '2026-12-04T15:40:00Z' : null,
          winner_display: null,
          slot_id: empty ? null : id,
          assignment_id: empty ? null : id,
          court_number: court,
          day_date: day,
          is_opening: court !== 6,
        })
        id += 1
      }
    }
  }
  return { slots, matches }
}

export default function CourtSheetPreviewPage() {
  const sample = useMemo(buildSample, [])
  const [slots, setSlots] = useState(sample.slots)
  const [matches, setMatches] = useState(sample.matches)
  const [day, setDay] = useState(DAYS[0])
  const [openMatch, setOpenMatch] = useState<DeskMatchItem | null>(null)
  const [notesOpen, setNotesOpen] = useState(false)
  const alex = { id: 42421, name: 'Alex Bose' }
  const jennifer = { id: 42422, name: 'Jennifer Myers' }
  const sampleNotes = [{ id: 1, playerId: alex.id, body: 'Arriving after announcements', createdAt: '2026-11-25T18:00:00Z', createdByName: 'Staff' }]
  const [score, setScore] = useState('8-6')
  const [started, setStarted] = useState(true)
  const [paused, setPaused] = useState(false)
  const days = listScheduleDays(slots)
  const schedule = buildDaySchedule({ day, slots, matches, closedCourtLabels: ['2'] })
  const ready = new Map(matches.filter((match) => match.team1_id && match.team2_id).map((match) => [match.match_id, true]))

  const move = (matchId: number, slotId: number) => {
    setSlots((prev) => prev.map((slot) => {
      if (slot.assigned_match_id === matchId) return { ...slot, assigned_match_id: null }
      if (slot.slot_id === slotId) return { ...slot, assigned_match_id: matchId }
      return slot
    }))
    setMatches((prev) => prev.map((match) => match.match_id === matchId ? { ...match, slot_id: slotId } : match))
  }

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', background: '#eceff1' }}>
      <div style={{ padding: '6px 10px', fontSize: 12, fontWeight: 800, color: '#1a237e' }}>
        Local sample Dashboard. This data is not a tournament and is not saved.
      </div>
      <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <DesignatedCourtSheet
            schedule={schedule}
            days={days}
            selectedDay={day}
            onSelectDay={setDay}
            checkinReadyByMatchId={ready}
            matches={matches}
            nowMinutes={9 * 60 + 20}
            isToday={day === DAYS[0]}
            clockLabel="9:20 AM"
            syncedLabel="Sample"
            isDraft
            busyMatchId={null}
            canUndo={false}
            onOpenMatch={setOpenMatch}
            onStart={(matchId) => setMatches((prev) => prev.map((match) => match.match_id === matchId ? { ...match, status: 'IN_PROGRESS' } : match))}
            onMove={move}
            onSwap={(matchId, occupantId) => {
              const left = matches.find((match) => match.match_id === matchId)
              const right = matches.find((match) => match.match_id === occupantId)
              if (!left?.slot_id || !right?.slot_id) return
              move(matchId, right.slot_id)
              move(occupantId, left.slot_id)
            }}
            onUndo={() => undefined}
            onCourtState={() => undefined}
            dayStarted={started}
            isCopy
            testClock="09:20"
            dayPaused={paused}
            arrivedTeamIds={matches.flatMap((match) => [match.team1_id, match.team2_id].filter((id): id is number => id != null))}
            onStartDay={() => setStarted(true)}
            onSetPaused={setPaused}
            rosterByTeam={{ 4242: [alex, jennifer] }}
            notedPlayerIds={[alex.id]}
            onOpenNotes={() => setNotesOpen(true)}
          />
        </div>
        {openMatch && (
          <aside data-testid="score-drawer" style={{ width: 280, background: '#fff', borderLeft: '1px solid #cfd8dc', padding: 12 }}>
            <div style={{ fontWeight: 800, marginBottom: 8 }}>Match #{openMatch.match_number}</div>
            <div style={{ fontSize: 13 }}>{openMatch.team1_display}</div>
            <div style={{ fontSize: 13, marginBottom: 8 }}>{openMatch.team2_display}</div>
            {openMatch.team1_id === 4242 && (
              <button type="button" onClick={() => setNotesOpen(true)} style={{ marginBottom: 8, border: '1px solid #f9a825', background: '#fff8e1', color: '#e65100', fontWeight: 800 }}>Notes</button>
            )}
            <input value={score} onChange={(event) => setScore(event.target.value)} style={{ width: '100%', marginBottom: 8 }} />
            <button
              type="button"
              onClick={() => {
                setMatches((prev) => prev.map((match) => match.match_id === openMatch.match_id ? { ...match, status: 'FINAL', score_display: score } : match))
                setOpenMatch(null)
              }}
            >
              Save final score
            </button>
          </aside>
        )}
      </div>
      {notesOpen && (
        <PlayerNotesDialog
          players={[alex, jennifer]}
          notes={sampleNotes}
          onClose={() => setNotesOpen(false)}
        />
      )}
    </div>
  )
}
