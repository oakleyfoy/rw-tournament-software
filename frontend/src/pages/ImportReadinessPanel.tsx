import { useState } from 'react'
import { aggregateImportReadiness, type RwOsReadinessTeam, type RwOsValidationIssue } from './rwOsImportReadiness'

export function ImportReadinessPanel({
  issues,
  teams,
}: {
  issues: RwOsValidationIssue[]
  teams: RwOsReadinessTeam[]
}) {
  const [open, setOpen] = useState(false)
  const readiness = aggregateImportReadiness(issues, teams)
  if (!readiness.warnings.length && !readiness.problems.length && !readiness.blocking.length) {
    return null
  }

  return (
    <div className="import-readiness" data-testid="import-readiness">
      <h4>Needs Attention</h4>
      {readiness.blocking.length > 0 && (
        <div className="import-readiness-blocking" data-testid="import-readiness-blocking">
          {readiness.blocking.map((group) => (
            <p key={group.code}>{group.summary}</p>
          ))}
        </div>
      )}
      {readiness.warnings.map((group) => (
        <p key={group.code} data-testid={`readiness-warning-${group.code}`}>
          {group.summary}
        </p>
      ))}
      {readiness.problems.length > 0 && (
        <div className="import-readiness-problems" data-testid="import-readiness-problems">
          {readiness.problems.map((group) => (
            <p key={group.code}>{group.summary}</p>
          ))}
        </div>
      )}
      {readiness.canProceed && (
        <p className="meta import-readiness-ok">
          {readiness.warnings.length
            ? 'Import can proceed. Missing towel color and Who Knows Who / Avoid Group are warnings and do not prevent import.'
            : 'Import can proceed.'}
        </p>
      )}
      <button className="link-button" type="button" onClick={() => setOpen((value) => !value)}>
        {open ? 'Hide Details' : 'View Details'}
      </button>
      {open && (
        <div className="import-readiness-details" data-testid="import-readiness-details">
          <table>
            <thead>
              <tr>
                <th>Team</th>
                <th>Player</th>
                <th>Issue</th>
              </tr>
            </thead>
            <tbody>
              {readiness.details.map((detail, index) => (
                <tr key={`${detail.code}-${detail.teamKey}-${detail.player}-${index}`}>
                  <td>{detail.teamName}</td>
                  <td>{detail.player || '—'}</td>
                  <td>{detail.issue}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
