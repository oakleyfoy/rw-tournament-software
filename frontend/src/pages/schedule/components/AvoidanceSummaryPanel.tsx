import { useState } from 'react'
import type { AvoidanceSummary } from '../../../api/client'

interface AvoidanceSummaryPanelProps {
  avoidanceSummary: AvoidanceSummary | null | undefined
  onFocusMatchIds: (matchIds: number[]) => void
}

export default function AvoidanceSummaryPanel({
  avoidanceSummary,
  onFocusMatchIds,
}: AvoidanceSummaryPanelProps) {
  const [copiedId, setCopiedId] = useState<string | null>(null)

  if (
    !avoidanceSummary ||
    (avoidanceSummary.r1_unavoidable_count === 0 &&
      avoidanceSummary.r2_potential_count === 0)
  ) {
    return null
  }

  const { r1_unavoidable_items, r2_potential_items } = avoidanceSummary

  function handleCopy(id: string, item: unknown) {
    navigator.clipboard.writeText(JSON.stringify(item, null, 2)).then(() => {
      setCopiedId(id)
      setTimeout(() => setCopiedId(null), 1500)
    })
  }

  const sectionStyle: React.CSSProperties = {
    marginBottom: 8,
  }

  const tableStyle: React.CSSProperties = {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: '0.82rem',
  }

  const thStyle: React.CSSProperties = {
    textAlign: 'left',
    padding: '4px 8px',
    borderBottom: '2px solid #888',
    fontWeight: 600,
    whiteSpace: 'nowrap',
  }

  const tdStyle: React.CSSProperties = {
    padding: '3px 8px',
    borderBottom: '1px solid #ddd',
    verticalAlign: 'middle',
  }

  const btnStyle: React.CSSProperties = {
    padding: '2px 8px',
    fontSize: '0.75rem',
    cursor: 'pointer',
    border: '1px solid #aaa',
    borderRadius: 3,
    background: '#f5f5f5',
    marginRight: 4,
  }

  return (
    <div
      style={{
        border: '1px solid #ccc',
        borderRadius: 6,
        padding: '12px 16px',
        marginBottom: 16,
        background: '#fefefe',
      }}
    >
      <h4 style={{ margin: '0 0 8px 0', fontSize: '1rem' }}>
        Avoidance Summary
      </h4>

      {/* WF R1 Section */}
      <details
        open={avoidanceSummary.r1_unavoidable_count > 0}
        style={sectionStyle}
      >
        <summary style={{ cursor: 'pointer', fontWeight: 500, fontSize: '0.9rem' }}>
          WF R1 &mdash; Unavoidable Conflicts ({avoidanceSummary.r1_unavoidable_count})
        </summary>
        {r1_unavoidable_items.length > 0 ? (
          <table style={tableStyle}>
            <thead>
              <tr>
                <th style={thStyle}>Match Code</th>
                <th style={thStyle}>Teams</th>
                <th style={thStyle}>Group</th>
                <th style={thStyle}>Seeds</th>
                <th style={thStyle}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {r1_unavoidable_items.map((item) => (
                <tr key={`r1-${item.match_id}`}>
                  <td style={{ ...tdStyle, fontFamily: 'monospace', fontSize: '0.78rem' }}>
                    {item.match_code}
                  </td>
                  <td style={tdStyle}>
                    {item.team_a ?? '?'} vs {item.team_b ?? '?'}
                  </td>
                  <td style={{ ...tdStyle, fontFamily: 'monospace' }}>
                    {item.avoid_group}
                  </td>
                  <td style={tdStyle}>
                    #{item.seed_a ?? '?'} vs #{item.seed_b ?? '?'}
                  </td>
                  <td style={{ ...tdStyle, whiteSpace: 'nowrap' }}>
                    <button
                      style={btnStyle}
                      onClick={() => onFocusMatchIds([item.match_id])}
                      title="Show in Inventory"
                    >
                      Show
                    </button>
                    <button
                      style={btnStyle}
                      onClick={() => handleCopy(`r1-${item.match_id}`, item)}
                      title="Copy JSON"
                    >
                      {copiedId === `r1-${item.match_id}` ? 'Copied' : 'Copy'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p style={{ fontSize: '0.85rem', color: '#888', margin: '4px 0' }}>
            No unavoidable conflicts.
          </p>
        )}
      </details>

      {/* WF R2 Section */}
      <details
        open={avoidanceSummary.r2_potential_count > 0}
        style={sectionStyle}
      >
        <summary style={{ cursor: 'pointer', fontWeight: 500, fontSize: '0.9rem' }}>
          WF R2 &mdash; Potential Conflicts ({avoidanceSummary.r2_potential_count})
        </summary>
        {r2_potential_items.length > 0 ? (
          <table style={tableStyle}>
            <thead>
              <tr>
                <th style={thStyle}>Match Code</th>
                <th style={thStyle}>Source R1</th>
                <th style={thStyle}>Overlap Groups</th>
                <th style={thStyle}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {r2_potential_items.map((item) => (
                <tr key={`r2-${item.match_id}`}>
                  <td style={{ ...tdStyle, fontFamily: 'monospace', fontSize: '0.78rem' }}>
                    {item.match_code}
                  </td>
                  <td style={{ ...tdStyle, fontFamily: 'monospace', fontSize: '0.78rem' }}>
                    {item.source_match_codes.join(', ')}
                  </td>
                  <td style={{ ...tdStyle, fontFamily: 'monospace' }}>
                    {item.overlap_groups.join(', ')}
                  </td>
                  <td style={{ ...tdStyle, whiteSpace: 'nowrap' }}>
                    <button
                      style={btnStyle}
                      onClick={() => onFocusMatchIds([item.match_id])}
                      title="Show in Inventory"
                    >
                      Show
                    </button>
                    <button
                      style={btnStyle}
                      onClick={() => handleCopy(`r2-${item.match_id}`, item)}
                      title="Copy JSON"
                    >
                      {copiedId === `r2-${item.match_id}` ? 'Copied' : 'Copy'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p style={{ fontSize: '0.85rem', color: '#888', margin: '4px 0' }}>
            No potential conflicts.
          </p>
        )}
      </details>
    </div>
  )
}
