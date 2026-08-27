import { useEffect, useState } from 'react'
import { getSlotVerification, type SlotVerificationResponse } from '../../../api/client'
import { timeTo12Hour } from '../../../utils/timeFormat'
import './ScheduleSlotVerification.css'

const WEEKDAYS = ['SUNDAY', 'MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY']

function weekdayLabel(isoDate: string): string {
  const [year, month, day] = isoDate.split('-').map(Number)
  return WEEKDAYS[new Date(year, month - 1, day).getDay()] || isoDate
}

function formatClock(value: string): string {
  return timeTo12Hour(value)
}

function StatusMark({ status }: { status: 'verified' | 'mismatch' }) {
  if (status === 'verified') {
    return <span className="slot-verification-ok">✓ VERIFIED</span>
  }
  return <span className="slot-verification-bad">⚠ MISMATCH</span>
}

function RowStatus({ status }: { status: 'verified' | 'mismatch' }) {
  if (status === 'verified') {
    return <span className="slot-verification-ok">✓</span>
  }
  return <span className="slot-verification-bad">⚠ MISMATCH</span>
}

interface Props {
  tournamentId: number
  versionId: number
  slotsCount: number
}

export function ScheduleSlotVerification({ tournamentId, versionId, slotsCount }: Props) {
  const [data, setData] = useState<SlotVerificationResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    getSlotVerification(tournamentId, versionId)
      .then((payload) => {
        if (!cancelled) {
          setData(payload)
          setError(null)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setData(null)
          setError(err instanceof Error ? err.message : 'Could not load slot verification')
        }
      })
    return () => {
      cancelled = true
    }
  }, [tournamentId, versionId, slotsCount])

  if (error) {
    return (
      <section className="slot-verification mismatch" aria-label="Court slot verification">
        <h3>COURT SLOT VERIFICATION</h3>
        <p className="slot-verification-empty">{error}</p>
      </section>
    )
  }

  if (!data) return null
  if (data.generated_slots === 0 && slotsCount === 0) return null

  return (
    <section
      className={`slot-verification${data.status === 'mismatch' ? ' mismatch' : ''}`}
      aria-label="Court slot verification"
    >
      <h3>COURT SLOT VERIFICATION</h3>
      <div className="slot-verification-total">
        <span>TOTAL COURT SLOTS</span>
        <span>Expected: {data.expected_slots}</span>
        <span>Generated: {data.generated_slots}</span>
        <StatusMark status={data.status} />
      </div>
      {data.days.map((day) => (
        <div key={day.day_date} className="slot-verification-day">
          <h4>{weekdayLabel(day.day_date)}</h4>
          <div className="slot-verification-day-summary">
            <span>Expected: {day.expected_slots}</span>
            <span>Generated: {day.generated_slots}</span>
            <StatusMark status={day.status} />
          </div>
          <table className="slot-verification-table">
            <thead>
              <tr>
                <th>TIME</th>
                <th className="num">COURTS</th>
                <th className="num">GENERATED</th>
                <th>STATUS</th>
              </tr>
            </thead>
            <tbody>
              {day.periods.map((period) => (
                <tr
                  key={`${period.source_kind}-${period.source_id}`}
                  className={period.status === 'mismatch' ? 'slot-verification-row-mismatch' : undefined}
                >
                  <td>
                    {formatClock(period.start_time)} – {formatClock(period.end_time)}
                    {period.blocks_per_court > 1 ? ` · ${period.blocks_per_court} blocks/court` : ''}
                  </td>
                  <td className="num">{period.courts}</td>
                  <td className="num">{period.generated_slots}</td>
                  <td>
                    <RowStatus status={period.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </section>
  )
}
