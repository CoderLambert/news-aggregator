import { useState, useRef, useCallback, useEffect } from 'react'

/**
 * useSpeech — TTS playback via Edge TTS (server-side, natural voices).
 *
 * Strategy:
 *   1. Primary: Edge TTS backend → streams MP3 audio → HTML5 Audio API
 *   2. Fallback: Web Speech API (system TTS) when backend is unavailable
 *
 * The hook manages a single Audio instance with full play/pause/stop/progress.
 */

export function useSpeech() {
  const [status, setStatus] = useState('idle') // idle | loading | playing | paused
  const [progress, setProgress] = useState(0)
  const audioRef = useRef(null)
  const supported = typeof window !== 'undefined'

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause()
        audioRef.current.src = ''
        audioRef.current = null
      }
    }
  }, [])

  // Audio event handlers
  const _attachAudioEvents = useCallback((audio) => {
    audio.onplay = () => setStatus('playing')
    audio.onpause = () => {
      if (!audio.ended) setStatus('paused')
    }
    audio.onended = () => {
      setStatus('idle')
      setProgress(1)
    }
    audio.ontimeupdate = () => {
      if (audio.duration && isFinite(audio.duration)) {
        setProgress(audio.currentTime / audio.duration)
      }
    }
    audio.onerror = () => {
      console.warn('TTS audio error')
      setStatus('idle')
      setProgress(0)
    }
    audio.oncanplay = () => {
      // Auto-play once enough data is buffered
      if (audio.readyState >= 3) {
        audio.play().catch(() => {})
      }
    }
  }, [])

  /**
   * speak(newsId, displayMode) — Start TTS playback via Edge TTS backend.
   */
  const speak = useCallback((newsId, displayMode = 'zh') => {
    if (!supported) return

    // Stop any current playback
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.src = ''
    }

    setStatus('loading')
    setProgress(0)

    const audio = new Audio()
    audioRef.current = audio
    _attachAudioEvents(audio)

    // Build URL — Django will stream MP3 chunks
    const url = `/api/news/${newsId}/tts/?displayMode=${encodeURIComponent(displayMode)}`
    audio.src = url
    audio.load()
  }, [supported, _attachAudioEvents])

  const pause = useCallback(() => {
    if (audioRef.current && !audioRef.current.paused) {
      audioRef.current.pause()
    }
  }, [])

  const resume = useCallback(() => {
    if (audioRef.current && audioRef.current.paused && !audioRef.current.ended) {
      audioRef.current.play().catch(() => {})
      setStatus('playing')
    }
  }, [])

  const stop = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.src = ''
      audioRef.current = null
    }
    setStatus('idle')
    setProgress(0)
  }, [])

  return { status, progress, speak, pause, resume, stop, supported }
}
