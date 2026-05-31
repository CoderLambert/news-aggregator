// Shared constants — single source of truth.
// LANG_KEY was previously exported from LanguageContext, creating a circular
// dependency with services/api.js. Moved here.

export const LANG_KEY = 'newshub_lang'

// Translation auto-resume marker (localStorage)
export const TRANSLATING_MARKER_PREFIX = 'translating_'
export const TRANSLATING_MARKER_TTL_MS = 5 * 60 * 1000 // 5 min
export const TRANSLATION_COMPLETE_MIN_LENGTH = 50

// SSE
export const SSE_PROGRESS_THROTTLE_MS = 200

export const translatingMarkerKey = (id) => `${TRANSLATING_MARKER_PREFIX}${id}`
