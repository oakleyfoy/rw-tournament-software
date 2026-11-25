import { useMemo, useState } from 'react'
import FirstMatchCheckIn from './ArrivalCheckIn'
import type { ArrivalPlayer, ArrivalTile } from './firstMatchCheckIn'
import type { CheckInMatchItem, DeskMatchItem, MatchCheckInSideState, PlayerCheckInState } from '../../api/client'

const FIRST = [
  'Carol', 'Olivia', 'Jennifer', 'Helen', 'Amy', 'Holly', 'Julie', 'Lisa',
  'Marisela', 'Michelle', 'Susan', 'Laura', 'Anne', 'Jessica', 'Janine', 'Jill',
  'Kerri', 'Flavia', 'Amalia', 'Victoria', 'Sarah', 'Elizabeth', 'Stephanie', 'Karen',
  'Frank', 'Vicky', 'Jeff', 'Kipsy', 'Gina', 'Tracy', 'Catherine', 'Paula',
  'Diane', 'Nancy', 'Betty', 'Ruth', 'Sharon', 'Donna', 'Carolyn', 'Deborah',
  'Janet', 'Maria', 'Heather', 'Teresa', 'Gloria', 'Evelyn', 'Jean', 'Cheryl',
  'Martha', 'Andrea', 'Kathryn', 'Judith',
]
const LAST = ['Smith', 'Jones', 'Hanna', 'Price', 'Clark', 'Moore', 'Webb', 'Stone', 'Vogel', 'Horn', 'Gould', 'Martin', 'OShea']
const TOWELS = ['Orange', 'Lime', 'Purple', 'Yellow', 'Red', 'Black', 'Blue', 'Pink', 'Green', 'Gray']

function person(index: number): PlayerCheckInState {
  const first = FIRST[index % FIRST.length]
  const last = LAST[Math.floor(index / FIRST.length) % LAST.length]
  return {
    player_id: 1000 + index,
    player_display: `${first} ${last}`,
    checked_in: false,
    checked_in_at: null,
    towel_color: TOWELS[index % TOWELS.length],
    report_url: null,
  }
}

function teamSide(side: 'A' | 'B', teamId: number, start: number): MatchCheckInSideState {
  const players = [person(start), person(start + 1)]
  return {
    side,
    team_id: teamId,
    team_display: players.map((player) => player.player_display).join(' / '),
    team_checked_in: false,
    team_checked_in_at: null,
    show_towels: true,
    players,
    players_checked_in: 0,
    players_total: 2,
    side_ready: false,
    ready_at: null,
  }
}

function buildBoard() {
  const waves = [
    { sort: '09:00:00', label: '9:00 AM', teams: 26 },
    { sort: '10:00:00', label: '10:00 AM', teams: 24 },
    { sort: '11:00:00', label: '11:00 AM', teams: 24 },
    { sort: '12:00:00', label: '12:00 PM', teams: 18 },
  ]
  const checkins: CheckInMatchItem[] = []
  const matches: DeskMatchItem[] = []
  let teamIndex = 0
  let matchId = 1
  for (const wave of waves) {
    for (let index = 0; index < wave.teams; index += 2) {
      const court = (index % 24) + 1
      const sideA = teamSide('A', 5000 + teamIndex, teamIndex * 2)
      const sideB = teamSide('B', 5000 + teamIndex + 1, (teamIndex + 1) * 2)
      teamIndex += 2
      checkins.push({
        match_id: matchId,
        match_number: matchId,
        match_code: `WOM_WF_R1_${matchId}`,
        event_name: wave.sort === '12:00:00' ? 'Mixed' : "Women's",
        day_label: 'Friday, December 4',
        scheduled_time: wave.label,
        sort_time: wave.sort,
        slot_id: matchId,
        side_a: sideA,
        side_b: sideB,
        match_ready: false,
        ready_at: null,
        checkin_enabled: true,
        is_opening_entry: true,
      })
      matches.push({
        match_id: matchId,
        match_number: matchId,
        match_code: `WOM_WF_R1_${matchId}`,
        stage: 'WF',
        event_id: 1,
        event_name: "Women's",
        division_name: null,
        day_index: 0,
        day_label: 'Friday, December 4',
        scheduled_time: wave.label,
        sort_time: wave.sort,
        court_name: `Court ${court}`,
        court_assignment_mode: 'PREASSIGNED',
        status: 'SCHEDULED',
        team1_id: sideA.team_id,
        team1_display: sideA.team_display,
        team2_id: sideB.team_id,
        team2_display: sideB.team_display,
        score_display: null,
        source_match_a_id: null,
        source_match_b_id: null,
        created_at: null,
        started_at: null,
        completed_at: null,
        winner_display: null,
        slot_id: matchId,
        assignment_id: matchId,
        court_number: court,
        day_date: '2026-12-04',
      })
      matchId += 1
    }
  }
  return { checkins, matches }
}

export default function CheckInPreviewPage() {
  const seed = useMemo(() => buildBoard(), [])
  const [checkins, setCheckins] = useState(seed.checkins)
  const mark = (player: ArrivalPlayer, checked: boolean) => {
    setCheckins((current) => current.map((match) => {
      if (match.match_id !== player.matchId) return match
      const apply = (side: MatchCheckInSideState) => ({
        ...side,
        players: side.players.map((item) => (
          item.player_id === player.playerId
            ? { ...item, checked_in: checked, checked_in_at: checked ? new Date().toISOString() : null }
            : item
        )),
      })
      return { ...match, side_a: apply(match.side_a), side_b: apply(match.side_b) }
    }))
  }
  return (
    <div style={{ height: '100vh' }}>
      <FirstMatchCheckIn
        checkins={checkins}
        matches={seed.matches}
        nowMinutes={9 * 60}
        isToday={() => true}
        pendingIds={[]}
        onCheckIn={(player) => mark(player, true)}
        onUndo={(player) => mark(player, false)}
        onCheckBoth={(tile: ArrivalTile) => {
          tile.players.filter((player) => !player.checkedIn).forEach((player) => mark(player, true))
        }}
      />
    </div>
  )
}
