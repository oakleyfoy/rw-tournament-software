export type Theme = {
  id: string
  name: string
  colors: {
    background: string
    text: string
    cardBackground: string
    primaryButton: string
    primaryButtonHover: string
    primaryButtonText: string
    secondaryButton: string
    secondaryButtonHover: string
    secondaryButtonText: string
    dangerButton: string
    dangerButtonHover: string
    tableHeader: string
    tableRowHover: string
    inputBorder: string
    inputBorderFocus: string
    inputBackground: string
    inputBackgroundFocus: string
    inputText: string
    sectionBorder: string
  }
}

export const themes: Theme[] = [
  {
    id: 'shells-version',
    name: "Shell's Version",
    colors: {
      background: '#bdddfc',
      text: '#384959',
      cardBackground: '#ffffff',
      primaryButton: '#6a89a7',
      primaryButtonHover: '#5a7897',
      primaryButtonText: '#ffffff',
      secondaryButton: '#88bdf2',
      secondaryButtonHover: '#78ade2',
      secondaryButtonText: '#ffffff',
      dangerButton: '#dc3545',
      dangerButtonHover: '#c82333',
      tableHeader: '#88bdf2',
      tableRowHover: '#bdddfc',
      inputBorder: '#88bdf2',
      inputBorderFocus: '#6a89a7',
      inputBackground: 'linear-gradient(135deg, #ffffff 0%, #f8f9ff 100%)',
      inputBackgroundFocus: 'linear-gradient(135deg, #ffffff 0%, #f0f4ff 100%)',
      inputText: '#384959',
      sectionBorder: '#6a89a7',
    },
  },
  {
    id: 'racquetwar',
    name: 'RacquetWar',
    colors: {
      background: '#000000',
      text: '#FFFFFF',
      cardBackground: '#000000',
      primaryButton: '#b5c525',
      primaryButtonHover: '#9da820',
      primaryButtonText: '#000000',
      secondaryButton: '#1a1a1a',
      secondaryButtonHover: '#2a2a2a',
      secondaryButtonText: '#FFFFFF',
      dangerButton: '#dc3545',
      dangerButtonHover: '#c82333',
      tableHeader: '#b5c525',
      tableRowHover: '#2a2a2a',
      inputBorder: '#b5c525',
      inputBorderFocus: '#FFFFFF',
      inputBackground: '#1a1a1a',
      inputBackgroundFocus: '#2a2a2a',
      inputText: '#FFFFFF',
      sectionBorder: '#b5c525',
    },
  },
  {
    id: 'american',
    name: 'American',
    colors: {
      background: '#e8f4f8',
      text: '#002868',
      cardBackground: '#ffffff',
      primaryButton: '#B22234',
      primaryButtonHover: '#9b1e2f',
      primaryButtonText: '#ffffff',
      secondaryButton: '#002868',
      secondaryButtonHover: '#001f4d',
      secondaryButtonText: '#ffffff',
      dangerButton: '#dc3545',
      dangerButtonHover: '#c82333',
      tableHeader: '#002868',
      tableRowHover: '#e8f4f8',
      inputBorder: '#002868',
      inputBorderFocus: '#B22234',
      inputBackground: 'linear-gradient(135deg, #ffffff 0%, #f0f7fa 100%)',
      inputBackgroundFocus: 'linear-gradient(135deg, #ffffff 0%, #e8f4f8 100%)',
      inputText: '#002868',
      sectionBorder: '#B22234',
    },
  },
]

export interface AppSettings {
  theme: string
}

const SETTINGS_KEY = 'rw-tournament-settings'
const DEFAULT_SETTINGS: AppSettings = {
  theme: 'shells-version',
}

export function getSettings(): AppSettings {
  try {
    const stored = localStorage.getItem(SETTINGS_KEY)
    if (stored) {
      const parsed = JSON.parse(stored)
      // Ensure we have valid settings (merge with defaults)
      return { ...DEFAULT_SETTINGS, ...parsed }
    }
  } catch (error) {
    console.error('Error loading settings:', error)
  }
  return DEFAULT_SETTINGS
}

export function saveSettings(settings: AppSettings): void {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings))
  } catch (error) {
    console.error('Error saving settings:', error)
  }
}

export function getTheme(themeId: string): Theme | undefined {
  return themes.find((t) => t.id === themeId)
}

export function getCurrentTheme(): Theme {
  const settings = getSettings()
  const theme = getTheme(settings.theme)
  return theme || themes[0] // Default to first theme if not found
}

export function applyTheme(theme: Theme): void {
  const root = document.documentElement
  root.style.setProperty('--theme-bg', theme.colors.background)
  root.style.setProperty('--theme-text', theme.colors.text)
  root.style.setProperty('--theme-card-bg', theme.colors.cardBackground)
  root.style.setProperty('--theme-primary-btn', theme.colors.primaryButton)
  root.style.setProperty('--theme-primary-btn-hover', theme.colors.primaryButtonHover)
  root.style.setProperty('--theme-primary-btn-text', theme.colors.primaryButtonText)
  root.style.setProperty('--theme-secondary-btn', theme.colors.secondaryButton)
  root.style.setProperty('--theme-secondary-btn-hover', theme.colors.secondaryButtonHover)
  root.style.setProperty('--theme-secondary-btn-text', theme.colors.secondaryButtonText)
  root.style.setProperty('--theme-danger-btn', theme.colors.dangerButton)
  root.style.setProperty('--theme-danger-btn-hover', theme.colors.dangerButtonHover)
  root.style.setProperty('--theme-table-header', theme.colors.tableHeader)
  root.style.setProperty('--theme-table-row-hover', theme.colors.tableRowHover)
  root.style.setProperty('--theme-input-border', theme.colors.inputBorder)
  root.style.setProperty('--theme-input-border-focus', theme.colors.inputBorderFocus)
  root.style.setProperty('--theme-input-bg', theme.colors.inputBackground)
  root.style.setProperty('--theme-input-bg-focus', theme.colors.inputBackgroundFocus)
  root.style.setProperty('--theme-input-text', theme.colors.inputText)
  root.style.setProperty('--theme-section-border', theme.colors.sectionBorder)
}

