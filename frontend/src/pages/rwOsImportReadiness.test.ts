import { describe, expect, it } from 'vitest'
import {
  aggregateImportReadiness,
  repeatedWarningMessages,
  TOWEL_WARNING_CODE,
  WKW_WARNING_CODE,
  type RwOsReadinessTeam,
  type RwOsValidationIssue,
} from './rwOsImportReadiness'

function issue(code: string, teamKey: string, message: string): RwOsValidationIssue {
  return { code, team_key: teamKey, message }
}

function team(
  teamKey: string,
  names: [string, string],
  towels: [string | null, string | null],
  displayName?: string,
): RwOsReadinessTeam {
  return {
    teamKey,
    displayName,
    player1: { name: names[0], towelColor: towels[0] },
    player2: { name: names[1], towel_color: towels[1] },
  }
}

describe('aggregateImportReadiness', () => {
  const teams = [
    team('1/2', ['Ada', 'Bea'], [null, 'Blue'], 'Ada / Bea'),
    team('3/4', ['Cara', 'Dee'], [null, null], 'Cara / Dee'),
    team('5/6', ['Eve', 'Fay'], ['Pink', 'Green'], 'Eve / Fay'),
    team('7/8', ['Gia', 'Hal'], ['Yellow', null], 'Gia / Hal'),
  ]

  const issues: RwOsValidationIssue[] = [
    issue(TOWEL_WARNING_CODE, '1/2', 'One or both players are missing a towel color.'),
    issue(TOWEL_WARNING_CODE, '3/4', 'One or both players are missing a towel color.'),
    issue(TOWEL_WARNING_CODE, '7/8', 'One or both players are missing a towel color.'),
    issue(WKW_WARNING_CODE, '1/2', 'Who knows who / avoid group is missing.'),
    issue(WKW_WARNING_CODE, '3/4', 'Who knows who / avoid group is missing.'),
    issue(WKW_WARNING_CODE, '5/6', 'Who knows who / avoid group is missing.'),
    issue('duplicate_rw_id', '5/6', 'RW_ID 99 appears on two active teams in the same draw.'),
  ]

  it('aggregates repeated warning sentences into counts', () => {
    const readiness = aggregateImportReadiness(issues, teams)
    expect(readiness.warnings).toHaveLength(2)
    expect(readiness.warnings.map((group) => group.summary)).toEqual([
      '4 players missing towel color',
      '3 teams missing Who Knows Who / Avoid Group',
    ])
    expect(repeatedWarningMessages(issues)).toEqual([
      'One or both players are missing a towel color.',
      'One or both players are missing a towel color.',
      'Who knows who / avoid group is missing.',
      'Who knows who / avoid group is missing.',
    ])
  })

  it('counts towel issues by affected player slots and WKW by teams', () => {
    const readiness = aggregateImportReadiness(issues, teams)
    const towel = readiness.warnings.find((group) => group.code === TOWEL_WARNING_CODE)
    const wkw = readiness.warnings.find((group) => group.code === WKW_WARNING_CODE)
    expect(towel?.count).toBe(4)
    expect(towel?.unit).toBe('player')
    expect(wkw?.count).toBe(3)
    expect(wkw?.unit).toBe('team')
  })

  it('identifies the affected team, player, and issue in details', () => {
    const readiness = aggregateImportReadiness(issues, teams)
    expect(readiness.details).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ teamName: 'Ada / Bea', player: 'Ada', issue: 'Missing towel color' }),
        expect.objectContaining({ teamName: 'Cara / Dee', player: 'Cara', issue: 'Missing towel color' }),
        expect.objectContaining({ teamName: 'Cara / Dee', player: 'Dee', issue: 'Missing towel color' }),
        expect.objectContaining({ teamName: 'Gia / Hal', player: 'Hal', issue: 'Missing towel color' }),
        expect.objectContaining({
          teamName: 'Eve / Fay',
          player: null,
          issue: 'Missing Who Knows Who / Avoid Group',
        }),
      ]),
    )
    expect(readiness.details.filter((detail) => detail.issue === 'Missing towel color')).toHaveLength(4)
  })

  it('keeps genuine problems separate and does not treat towel/WKW as blocking', () => {
    const readiness = aggregateImportReadiness(issues, teams)
    expect(readiness.canProceed).toBe(true)
    expect(readiness.blocking).toEqual([])
    expect(readiness.problems).toHaveLength(1)
    expect(readiness.problems[0].code).toBe('duplicate_rw_id')
    expect(readiness.problems[0].summary).toContain('RW_ID 99')
  })
})
