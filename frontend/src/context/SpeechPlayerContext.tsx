/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext } from 'react'
import type { DisplayMode } from '@/types/news'
import type { PlaybackRate, SpeechScope, VoiceKey } from '@/constants/tts'
import type { NewsId } from '@/services/api'

export type SpeechStatus = 'idle' | 'loading' | 'playing' | 'paused'

export interface SpeechPlayerState {
  status: SpeechStatus
  progress: number
  duration: number
  currentTime: number
  rate: PlaybackRate
  voice: VoiceKey
  scope: SpeechScope
  title: string
  newsId: NewsId | null
  displayMode: DisplayMode
}

export interface SpeechPlayerCapabilities {
  supported: boolean
}

export interface SpeechPlayerActions {
  speak: (newsId: NewsId, title: string, displayMode?: DisplayMode) => void
  pause: () => void
  resume: () => void
  stop: () => void
  seek: (fraction: number) => void
  setRate: (rate: PlaybackRate) => void
  setVoice: (voice: VoiceKey) => void
  setScope: (scope: SpeechScope) => void
}

export type SpeechPlayerContextValue = SpeechPlayerState & SpeechPlayerActions & SpeechPlayerCapabilities

const SpeechPlayerStateContext = createContext<SpeechPlayerState | null>(null)
const SpeechPlayerActionsContext = createContext<SpeechPlayerActions | null>(null)
const SpeechPlayerCapabilitiesContext = createContext<SpeechPlayerCapabilities | null>(null)

export { SpeechPlayerStateContext, SpeechPlayerActionsContext, SpeechPlayerCapabilitiesContext }

export function useSpeechPlayerState(): SpeechPlayerState {
  const state = useContext(SpeechPlayerStateContext)
  if (!state) throw new Error('useSpeechPlayerState must be used within <SpeechPlayerProvider>')
  return state
}

/** Subscribe to stable controls without re-rendering on each audio timeupdate. */
export function useSpeechPlayerActions(): SpeechPlayerActions {
  const actions = useContext(SpeechPlayerActionsContext)
  if (!actions) throw new Error('useSpeechPlayerActions must be used within <SpeechPlayerProvider>')
  return actions
}

export function useSpeechPlayerCapabilities(): SpeechPlayerCapabilities {
  const capabilities = useContext(SpeechPlayerCapabilitiesContext)
  if (!capabilities) throw new Error('useSpeechPlayerCapabilities must be used within <SpeechPlayerProvider>')
  return capabilities
}

/** Convenience hook for components that truly need both the state and controls. */
export function useSpeechPlayer(): SpeechPlayerContextValue {
  return { ...useSpeechPlayerState(), ...useSpeechPlayerActions(), ...useSpeechPlayerCapabilities() }
}
