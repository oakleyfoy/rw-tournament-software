import { ScheduleVersion, ScheduleSlot, Match } from '../../api/client'

export type { ScheduleVersion, ScheduleSlot }

export interface UnscheduledMatch extends Match {
  event_id: number
  match_code: string
  match_type: 'WF' | 'RR' | 'BRACKET' | 'PLACEMENT'
  duration_minutes: number
  status: 'unscheduled' | 'scheduled' | 'complete' | 'cancelled'
}

export interface BuildSummary {
  slots_created: number
  matches_created: number
  matches_assigned: number
  matches_unassigned: number
  conflicts?: {
    reason: string
    count: number
  }[]
  warnings?: {
    message: string
    count: number
  }[]
}

