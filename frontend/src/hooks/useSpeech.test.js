import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// ── Mock HTML5 Audio ─────────────────────────────────────────────────
const mockAudioInstances = []

class MockAudio {
  constructor() {
    this.src = ''
    this.paused = true
    this.ended = false
    this.readyState = 0
    this.currentTime = 0
    this.duration = NaN
    this.onplay = null
    this.onpause = null
    this.onended = null
    this.ontimeupdate = null
    this.onerror = null
    this.oncanplay = null
    mockAudioInstances.push(this)
  }
  play() { this.paused = false; return Promise.resolve() }
  pause() { this.paused = true }
  load() {
    this.readyState = 4
    // Simulate canplay → auto-play
    if (this.oncanplay) this.oncanplay()
  }
}

beforeEach(() => {
  mockAudioInstances.length = 0
  vi.stubGlobal('Audio', MockAudio)
})

afterEach(() => {
  vi.restoreAllMocks()
})

import { useSpeech } from './useSpeech'
import { act, renderHook } from '@testing-library/react'

describe('useSpeech', () => {
  it('initial state is idle', () => {
    const { result } = renderHook(() => useSpeech())
    expect(result.current.status).toBe('idle')
    expect(result.current.progress).toBe(0)
    expect(result.current.supported).toBe(true)
  })

  it('speak() creates Audio with correct TTS URL', () => {
    const { result } = renderHook(() => useSpeech())
    act(() => { result.current.speak(42, 'zh') })
    expect(mockAudioInstances).toHaveLength(1)
    expect(mockAudioInstances[0].src).toBe('/api/news/42/tts/?displayMode=zh')
  })

  it('speak() sets status to loading', () => {
    const { result } = renderHook(() => useSpeech())
    act(() => { result.current.speak(42, 'zh') })
    expect(result.current.status).toBe('loading')
  })

  it('Audio oncanplay triggers play → status=playing', () => {
    const { result } = renderHook(() => useSpeech())
    act(() => { result.current.speak(42, 'zh') })
    const audio = mockAudioInstances[0]
    act(() => { audio.onplay?.() })
    expect(result.current.status).toBe('playing')
  })

  it('Audio onended → status=idle, progress=1', () => {
    const { result } = renderHook(() => useSpeech())
    act(() => { result.current.speak(42, 'zh') })
    const audio = mockAudioInstances[0]
    act(() => { audio.onended?.() })
    expect(result.current.status).toBe('idle')
    expect(result.current.progress).toBe(1)
  })

  it('pause() pauses audio', () => {
    const { result } = renderHook(() => useSpeech())
    act(() => { result.current.speak(42, 'zh') })
    const audio = mockAudioInstances[0]
    act(() => { audio.onplay?.() }) // status = playing
    act(() => { result.current.pause() })
    expect(audio.paused).toBe(true)
  })

  it('resume() plays audio again', () => {
    const { result } = renderHook(() => useSpeech())
    act(() => { result.current.speak(42, 'zh') })
    const audio = mockAudioInstances[0]
    act(() => { audio.onplay?.() })
    act(() => { result.current.pause() })
    act(() => { result.current.resume() })
    expect(result.current.status).toBe('playing')
  })

  it('stop() resets to idle', () => {
    const { result } = renderHook(() => useSpeech())
    act(() => { result.current.speak(42, 'zh') })
    act(() => { result.current.stop() })
    expect(result.current.status).toBe('idle')
    expect(result.current.progress).toBe(0)
  })

  it('speak() stops previous audio before new one', () => {
    const { result } = renderHook(() => useSpeech())
    act(() => { result.current.speak(1, 'zh') })
    const audio1 = mockAudioInstances[0]
    act(() => { audio1.onplay?.() })
    act(() => { result.current.speak(2, 'zh') })
    // First audio should be paused and src cleared
    expect(audio1.src).toBe('')
  })

  it('progress updates from ontimeupdate', () => {
    const { result } = renderHook(() => useSpeech())
    act(() => { result.current.speak(42, 'zh') })
    const audio = mockAudioInstances[0]
    audio.duration = 100
    audio.currentTime = 30
    act(() => { audio.ontimeupdate?.() })
    expect(result.current.progress).toBeCloseTo(0.3, 1)
  })

  it('handles audio error gracefully', () => {
    const { result } = renderHook(() => useSpeech())
    act(() => { result.current.speak(42, 'zh') })
    const audio = mockAudioInstances[0]
    act(() => { audio.onerror?.() })
    expect(result.current.status).toBe('idle')
  })

  it('cleans up audio on unmount', () => {
    const { result, unmount } = renderHook(() => useSpeech())
    act(() => { result.current.speak(42, 'zh') })
    const audio = mockAudioInstances[0]
    unmount()
    expect(audio.paused).toBe(true)
    expect(audio.src).toBe('')
  })

  it('speak() with displayMode=original', () => {
    const { result } = renderHook(() => useSpeech())
    act(() => { result.current.speak(42, 'original') })
    expect(mockAudioInstances[0].src).toContain('displayMode=original')
  })
})
