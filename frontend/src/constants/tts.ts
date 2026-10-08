export const VOICE_KEY = 'newshub_tts_voice'
export const RATE_KEY = 'newshub_tts_rate'
export const POSITION_KEY_PREFIX = 'newshub_tts_pos_'
export const SCOPE_KEY = 'newshub_tts_scope'

export const VOICES = [
  { key: 'yunyang', label: '云扬', desc: '新闻男声' },
  { key: 'xiaoxiao', label: '晓晓', desc: '亲切女声' },
  { key: 'yunxi', label: '云希', desc: '青年男声' },
] as const

export const RATES = [0.8, 1.0, 1.2, 1.5, 2.0] as const

export const SCOPES = [
  { key: 'full', label: '全文' },
  { key: 'summary', label: '摘要' },
] as const

export type VoiceKey = (typeof VOICES)[number]['key']
export type PlaybackRate = (typeof RATES)[number]
export type SpeechScope = (typeof SCOPES)[number]['key']
