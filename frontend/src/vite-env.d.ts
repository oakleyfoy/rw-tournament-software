/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  /** Set to "true" to enable Manual Schedule Editor (Phase 3E) for limited-audience deploy */
  readonly VITE_ENABLE_MANUAL_EDITOR?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

