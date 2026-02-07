import type { ScheduleBuilderEvent } from '../api/client'

interface ScheduleBuilderTableProps {
  events: ScheduleBuilderEvent[]
}

export default function ScheduleBuilderTable({ events }: ScheduleBuilderTableProps) {
  const totals = events.reduce(
    (acc, e) => ({
      wf_matches: acc.wf_matches + (e.wf_matches ?? 0),
      bracket_matches: acc.bracket_matches + (e.bracket_matches ?? 0),
      round_robin_matches: acc.round_robin_matches + (e.round_robin_matches ?? 0),
      total_matches: acc.total_matches + (e.total_matches ?? 0),
    }),
    { wf_matches: 0, bracket_matches: 0, round_robin_matches: 0, total_matches: 0 }
  )

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 720 }}>
        <thead>
          <tr style={{ borderBottom: '2px solid #333', textAlign: 'left' }}>
            <th style={{ padding: '8px 12px' }}>Event</th>
            <th style={{ padding: '8px 12px' }}>Teams</th>
            <th style={{ padding: '8px 12px' }}>Template</th>
            <th style={{ padding: '8px 12px' }}>WF Matches</th>
            <th style={{ padding: '8px 12px' }}>Bracket Matches</th>
            <th style={{ padding: '8px 12px' }}>RR Matches</th>
            <th style={{ padding: '8px 12px' }}>Total Matches</th>
            <th style={{ padding: '8px 12px' }}>WF Length</th>
            <th style={{ padding: '8px 12px' }}>Std Length</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr
              key={e.event_id}
              style={{
                borderBottom: '1px solid #ddd',
                backgroundColor: e.error
                  ? 'rgba(255, 0, 0, 0.08)'
                  : e.warning
                  ? 'rgba(255, 200, 0, 0.08)'
                  : undefined,
              }}
            >
              <td style={{ padding: '8px 12px' }}>
                {e.event_name}
                {e.status && !e.is_finalized && (
                  <span style={{ marginLeft: 8, fontSize: '11px', color: '#888' }}>({e.status})</span>
                )}
                {e.error != null && (
                  <div style={{ fontSize: '12px', color: '#c00', marginTop: 4 }}>{e.error}</div>
                )}
                {e.warning != null && !e.error && (
                  <div style={{ fontSize: '12px', color: '#a80', marginTop: 4 }}>{e.warning}</div>
                )}
              </td>
              <td style={{ padding: '8px 12px' }}>{e.team_count}</td>
              <td style={{ padding: '8px 12px' }}>{e.template_type}</td>
              <td style={{ padding: '8px 12px' }}>{e.wf_matches ?? '—'}</td>
              <td style={{ padding: '8px 12px' }}>{e.bracket_matches ?? '—'}</td>
              <td style={{ padding: '8px 12px' }}>{e.round_robin_matches ?? '—'}</td>
              <td style={{ padding: '8px 12px' }}>{e.total_matches ?? '—'}</td>
              <td style={{ padding: '8px 12px' }}>{e.match_lengths?.waterfall ?? '—'} min</td>
              <td style={{ padding: '8px 12px' }}>{e.match_lengths?.standard ?? '—'} min</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr style={{ borderTop: '2px solid #333', fontWeight: 600 }}>
            <td style={{ padding: '8px 12px' }}>Totals</td>
            <td style={{ padding: '8px 12px' }}>—</td>
            <td style={{ padding: '8px 12px' }}>—</td>
            <td style={{ padding: '8px 12px' }}>{totals.wf_matches}</td>
            <td style={{ padding: '8px 12px' }}>{totals.bracket_matches}</td>
            <td style={{ padding: '8px 12px' }}>{totals.round_robin_matches}</td>
            <td style={{ padding: '8px 12px' }}>{totals.total_matches}</td>
            <td style={{ padding: '8px 12px' }}>—</td>
            <td style={{ padding: '8px 12px' }}>—</td>
          </tr>
        </tfoot>
      </table>
    </div>
  )
}
