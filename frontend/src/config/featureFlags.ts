/**
 * Feature Flags
 * 
 * Environment-based feature toggles for controlled rollout.
 * Set via environment variables at build time.
 */

const raw = (import.meta as any).env?.VITE_ENABLE_MANUAL_EDITOR;

export const featureFlags = {
  /**
   * Manual Schedule Editor (Phase 3E)
   * 
   * Enables the drag-and-drop manual schedule editor UI.
   * Set VITE_ENABLE_MANUAL_EDITOR=true to enable.
   * 
   * Default: false (disabled)
   */
  manualScheduleEditor: raw === "true", // Strict: only "true" string enables
};

// TEMP (Step 4): Export raw string for debug UI
export const featureFlagsRaw = {
  VITE_ENABLE_MANUAL_EDITOR: raw,
};

