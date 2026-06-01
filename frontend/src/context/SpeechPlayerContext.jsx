import { createContext, useContext } from 'react'

/**
 * SpeechPlayerContext — global TTS state.
 *
 * Value shape:
 * {
 *   status: 'idle' | 'loading' | 'playing' | 'paused',
 *   progress: number,         // 0–1
 *   duration: number,         // seconds
 *   currentTime: number,      // seconds
 *   rate: number,             // playback rate
 *   voice: string,            // current voice key
 *   title: string,            // article title being played
 *   newsId: number | null,    // article id
 *   displayMode: string,      // display mode used for TTS
 *   speak: (newsId: number, title: string, displayMode?: string) => void,
 *   pause: () => void,
 *   resume: () => void,
 *   stop: () => void,
 *   seek: (fraction: number) => void,   // jump to position 0–1
 *   setRate: (rate: number) => void,
 *   setVoice: (voice: string) => void,
 *   supported: boolean,
 * }
 */
export const SpeechPlayerContext = createContext(null)

export function useSpeechPlayer() {
  const ctx = useContext(SpeechPlayerContext)
  if (!ctx) {
    throw new Error('useSpeechPlayer must be used within SpeechPlayerProvider')
  }
  return ctx
}
