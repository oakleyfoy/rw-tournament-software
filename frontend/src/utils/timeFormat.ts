/**
 * Utility functions for time formatting
 */

/**
 * Convert minutes to a human-readable duration string with hours and fractions
 * Examples: 30 -> "1/2 Hour", 60 -> "1 Hour", 90 -> "1 1/2 Hours", 120 -> "2 Hours"
 */
export function minutesToHours(minutes: number): string {
  if (minutes < 60) {
    // Less than an hour - show as fraction
    if (minutes === 30) {
      return '1/2 Hour'
    } else if (minutes === 15) {
      return '1/4 Hour'
    } else if (minutes === 45) {
      return '3/4 Hour'
    } else {
      return `${minutes} Min`
    }
  }
  
  const hours = Math.floor(minutes / 60)
  const remainingMinutes = minutes % 60
  
  if (remainingMinutes === 0) {
    return hours === 1 ? '1 Hour' : `${hours} Hours`
  } else if (remainingMinutes === 30) {
    return hours === 0 ? '1/2 Hour' : `${hours} 1/2 Hours`
  } else if (remainingMinutes === 15) {
    return hours === 0 ? '1/4 Hour' : `${hours} 1/4 Hours`
  } else if (remainingMinutes === 45) {
    return hours === 0 ? '3/4 Hour' : `${hours} 3/4 Hours`
  } else {
    // For other fractions, show as decimal
    const totalHours = (minutes / 60).toFixed(1)
    return totalHours === '1.0' ? '1 Hour' : `${totalHours} Hours`
  }
}

/**
 * Convert a time string (HH:mm) to 12-hour format with AM/PM
 * Example: "14:30" -> "2:30 PM"
 */
export function timeTo12Hour(timeStr: string): string {
  if (!timeStr) return ''
  
  const [hours, minutes] = timeStr.split(':').map(Number)
  if (isNaN(hours) || isNaN(minutes)) return timeStr
  
  const period = hours >= 12 ? 'PM' : 'AM'
  const displayHours = hours === 0 ? 12 : hours > 12 ? hours - 12 : hours
  
  return `${displayHours}:${String(minutes).padStart(2, '0')} ${period}`
}

/**
 * Convert minutes to clock time format (for backwards compatibility)
 * @deprecated Use minutesToHours instead for schedule grid
 */
export function minutesToClock(minutes: number): string {
  return minutesToHours(minutes)
}

/**
 * Convert minutes to H:MM format (for match durations)
 * Examples: 60 -> "1:00", 90 -> "1:30", 105 -> "1:45", 120 -> "2:00"
 */
export function minutesToHM(minutes: number): string {
  const hours = Math.floor(minutes / 60)
  const mins = minutes % 60
  return `${hours}:${String(mins).padStart(2, '0')}`
}

/**
 * Convert minutes to fractional hours (for display)
 * Examples: 60 -> 1.0, 90 -> 1.5, 105 -> 1.75, 120 -> 2.0
 */
export function minutesToFractionalHours(minutes: number): number {
  return minutes / 60
}