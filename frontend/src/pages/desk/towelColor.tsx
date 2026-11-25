function hexToRgb(hex: string): { r: number; g: number; b: number } | null {
  const normalized = hex.replace('#', '').trim()
  if (!/^[0-9a-f]{3}([0-9a-f]{3})?$/i.test(normalized)) return null
  const full = normalized.length === 3
    ? normalized.split('').map((ch) => ch + ch).join('')
    : normalized
  return {
    r: parseInt(full.slice(0, 2), 16),
    g: parseInt(full.slice(2, 4), 16),
    b: parseInt(full.slice(4, 6), 16),
  }
}

function isLightRgb(r: number, g: number, b: number): boolean {
  const luminance = (0.299 * r) + (0.587 * g) + (0.114 * b)
  return luminance >= 186
}

function deriveDynamicTowelStyles(rawColor: string): { backgroundColor: string; color: string; borderColor: string } | null {
  const trimmed = rawColor.trim()
  if (!trimmed) return null

  const normalized = trimmed.toLowerCase()
  const aliasMap: Record<string, string> = {
    neonyellow: '#d4ff2a',
    neonlime: '#c6ff00',
    lightblue: '#64b5f6',
    babyblue: '#81d4fa',
    skyblue: '#4fc3f7',
    darkblue: '#0d47a1',
    huntergreen: '#355e3b',
    forestgreen: '#2e7d32',
    darkgreen: '#1b5e20',
    lightgreen: '#8bc34a',
    hotpink: '#ec407a',
    maroon: '#800000',
    tan: '#d2b48c',
    gold: '#fbc02d',
    silver: '#b0bec5',
  }

  const candidates = [
    trimmed,
    normalized,
    normalized.replace(/\s+/g, ''),
    normalized.replace(/[^a-z0-9#(),.%\s-]/g, '').trim(),
  ].filter((value, index, arr) => value && arr.indexOf(value) === index)

  for (const candidate of candidates) {
    const alias = aliasMap[candidate.replace(/\s+/g, '')]
    const resolved = alias || candidate
    const rgb = hexToRgb(resolved)
    if (rgb) {
      const light = isLightRgb(rgb.r, rgb.g, rgb.b)
      return {
        backgroundColor: resolved,
        color: light ? '#1f2937' : '#ffffff',
        borderColor: light ? 'rgba(15, 23, 42, 0.28)' : 'rgba(255, 255, 255, 0.16)',
      }
    }
    if (typeof window !== 'undefined' && typeof window.CSS !== 'undefined' && window.CSS.supports('color', resolved)) {
      const lowerResolved = resolved.toLowerCase()
      const lightKeyword = /(white|yellow|lime|mint|gold|silver|cream|ivory|tan|beige|khaki|sky|baby|light)/.test(lowerResolved)
      return {
        backgroundColor: resolved,
        color: lightKeyword ? '#1f2937' : '#ffffff',
        borderColor: lightKeyword ? 'rgba(15, 23, 42, 0.28)' : 'rgba(255, 255, 255, 0.16)',
      }
    }
  }

  return null
}

export function getTowelPillStyles(colorName: string): { backgroundColor: string; color: string; borderColor: string } {
  const key = colorName.trim().toLowerCase()
  const presets: Record<string, { backgroundColor: string; color: string; borderColor: string }> = {
    lime: { backgroundColor: '#c6ff00', color: '#1b1b1b', borderColor: '#99cc00' },
    black: { backgroundColor: '#111111', color: '#ffffff', borderColor: '#000000' },
    royal: { backgroundColor: '#4169e1', color: '#ffffff', borderColor: '#2746a6' },
    navy: { backgroundColor: '#001f5b', color: '#ffffff', borderColor: '#00143d' },
    red: { backgroundColor: '#d32f2f', color: '#ffffff', borderColor: '#9a0007' },
    purple: { backgroundColor: '#8e24aa', color: '#ffffff', borderColor: '#5c007a' },
    orange: { backgroundColor: '#ef6c00', color: '#ffffff', borderColor: '#b53d00' },
    pine: { backgroundColor: '#1b5e20', color: '#ffffff', borderColor: '#0d3b12' },
    yellow: { backgroundColor: '#ffd54f', color: '#2f2400', borderColor: '#c8a415' },
    gray: { backgroundColor: '#757575', color: '#ffffff', borderColor: '#4a4a4a' },
    grey: { backgroundColor: '#757575', color: '#ffffff', borderColor: '#4a4a4a' },
    blue: { backgroundColor: '#1976d2', color: '#ffffff', borderColor: '#0d47a1' },
    green: { backgroundColor: '#2e7d32', color: '#ffffff', borderColor: '#1b5e20' },
    pink: { backgroundColor: '#d81b60', color: '#ffffff', borderColor: '#8e0038' },
    white: { backgroundColor: '#fafafa', color: '#455a64', borderColor: '#cfd8dc' },
  }
  return presets[key] || deriveDynamicTowelStyles(colorName) || { backgroundColor: '#eef2f7', color: '#334155', borderColor: '#cbd5e1' }
}

export function TowelColorPill({
  colorName,
  reportUrl,
  labelMode = 'full',
  eggHeight,
}: {
  colorName: string | null
  reportUrl?: string | null
  labelMode?: 'full' | 'swatch' | 'egg'
  eggHeight?: number
}) {
  if (!colorName) return null
  const styles = getTowelPillStyles(colorName)
  const clickable = !!reportUrl
  const height = eggHeight ?? (labelMode === 'egg' ? 18 : labelMode === 'swatch' ? 14 : undefined)
  const width = labelMode === 'egg' ? Math.max(14, (height || 18) - 2) : labelMode === 'swatch' ? 24 : undefined
  return (
    <span
      title={clickable ? `Open report: ${reportUrl}` : colorName}
      onClick={clickable ? () => window.open(reportUrl!, '_blank', 'noopener,noreferrer') : undefined}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: labelMode === 'full' ? '1px 7px' : 0,
        borderRadius: 999,
        border: `1px solid ${styles.borderColor}`,
        backgroundColor: styles.backgroundColor,
        color: styles.color,
        fontSize: 10,
        fontWeight: 700,
        lineHeight: labelMode === 'full' ? '16px' : 0,
        cursor: clickable ? 'pointer' : 'default',
        whiteSpace: 'nowrap',
        minWidth: width,
        width,
        height,
        flexShrink: 0,
      }}
    >
      {labelMode === 'full' ? colorName : ''}
    </span>
  )
}

export function TowelCountBar({ colorName, count, maxCount }: { colorName: string; count: number; maxCount: number }) {
  const styles = getTowelPillStyles(colorName)
  const widthPct = maxCount > 0 ? Math.max((count / maxCount) * 100, count > 0 ? 8 : 0) : 0
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'auto minmax(80px, 1fr) 32px', alignItems: 'center', gap: 8 }}>
      <TowelColorPill colorName={colorName} />
      <div style={{ height: 12, borderRadius: 999, backgroundColor: '#edf2f7', overflow: 'hidden', border: '1px solid #e2e8f0' }}>
        <div style={{ height: '100%', width: `${widthPct}%`, backgroundColor: styles.backgroundColor, borderRight: `1px solid ${styles.borderColor}` }} />
      </div>
      <span style={{ fontSize: 12, fontWeight: 700, color: '#334155', textAlign: 'right' }}>{count}</span>
    </div>
  )
}
