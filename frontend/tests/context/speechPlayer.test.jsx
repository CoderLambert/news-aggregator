import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useState } from 'react'
import { AuthContext } from '@/context/AuthContext'
import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SpeechPlayerProvider } from '@/context/SpeechPlayerProvider'
import { useSpeechPlayerActions, useSpeechPlayerState } from '@/context/SpeechPlayerContext'
import GlobalSpeechPlayer from '@/components/speech/GlobalSpeechPlayer'

const audioInstances = []
let deferNextAudioMetadata = false
const mediaSession = {
  actionHandlers: new Map(),
  metadata: null,
  setActionHandler(action, handler) {
    if (handler) this.actionHandlers.set(action, handler)
    else this.actionHandlers.delete(action)
  },
}
let previousMediaSessionDescriptor

function deferred() {
  let reject
  const promise = new Promise((_, rejectPromise) => { reject = rejectPromise })
  return { promise, reject }
}

class MockAudio {
  constructor() {
    this.src = ''
    this.paused = true
    this.ended = false
    this.currentTime = 0
    this.duration = 120
    this.playbackRate = 1
    this.onplay = null
    this.onpause = null
    this.onended = null
    this.ontimeupdate = null
    this.onerror = null
    this.onloadedmetadata = null
    audioInstances.push(this)
  }

  play() {
    this.paused = false
    this.onplay?.()
    return Promise.resolve()
  }

  pause() {
    const wasPlaying = !this.paused
    this.paused = true
    if (wasPlaying) this.onpause?.()
  }

  load() {
    if (!this.src) return
    if (deferNextAudioMetadata) {
      deferNextAudioMetadata = false
      return
    }
    this.onloadedmetadata?.()
  }

  removeAttribute(name) {
    if (name === 'src') this.src = ''
  }
}

function PlayerActions() {
  const player = useSpeechPlayerActions()
  const state = useSpeechPlayerState()
  return (
    <div>
      <button type="button" onClick={() => player.speak(11, '第一篇虚构新闻', { language: 'zh' })}>朗读第一篇</button>
      <button type="button" onClick={() => player.speak(12, '第二篇虚构新闻', { language: 'original' })}>朗读第二篇</button>
      <button type="button" onClick={() => player.speak(11, '译文版本 A', { language: 'zh', scope: 'full', translationResultId: 41 })}>朗读译文 A</button>
      <button type="button" onClick={() => player.speak(11, '译文版本 B', { language: 'zh', scope: 'full', translationResultId: 42 })}>朗读译文 B</button>
      <button type="button" onClick={player.stop}>停止播放器</button>
      <output data-testid="player-status">{state.status}</output>
    </div>
  )
}

function TestAuthProvider({ children }) {
  const [user, setUser] = useState({ id: 101, username: 'viewer-a', isSuperuser: false })
  return (
    <AuthContext.Provider value={{
      user, loading: false, login: async () => user, register: async () => user,
      logout: async () => setUser(null), refresh: async () => {},
    }}>
      <button type="button" onClick={() => setUser({ id: 202, username: 'viewer-b', isSuperuser: false })}>切换用户</button>
      {children}
    </AuthContext.Provider>
  )
}

function renderPlayer() {
  return render(
    <TestAuthProvider>
      <SpeechPlayerProvider>
        <PlayerActions />
        <GlobalSpeechPlayer />
      </SpeechPlayerProvider>
    </TestAuthProvider>,
  )
}

beforeEach(() => {
  audioInstances.length = 0
  deferNextAudioMetadata = false
  localStorage.clear()
  vi.stubGlobal('Audio', MockAudio)
  previousMediaSessionDescriptor = Object.getOwnPropertyDescriptor(navigator, 'mediaSession')
  mediaSession.actionHandlers.clear()
  mediaSession.metadata = null
  Object.defineProperty(navigator, 'mediaSession', { configurable: true, value: mediaSession })
})

afterEach(() => {
  if (previousMediaSessionDescriptor) {
    Object.defineProperty(navigator, 'mediaSession', previousMediaSessionDescriptor)
  } else {
    Reflect.deleteProperty(navigator, 'mediaSession')
  }
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('global speech player', () => {
  it('keeps one global track across pause, resume, article switches and stop', async () => {
    const user = userEvent.setup()
    renderPlayer()

    await user.click(screen.getByRole('button', { name: '朗读第一篇' }))
    expect(await screen.findByRole('region', { name: '全局语音播放器' })).toHaveTextContent('第一篇虚构新闻')
    expect(screen.getByTestId('player-status')).toHaveTextContent('playing')
    expect(audioInstances[0].src).toContain('/api/news/11/tts/?language=zh&voice=yunyang&scope=full')

    await user.click(screen.getByRole('button', { name: '暂停语音' }))
    expect(screen.getByRole('button', { name: '继续播放语音' })).toBeInTheDocument()
    expect(screen.getByTestId('player-status')).toHaveTextContent('paused')

    await user.click(screen.getByRole('button', { name: '继续播放语音' }))
    await user.click(screen.getByRole('button', { name: '朗读第二篇' }))
    expect(await screen.findByText('第二篇虚构新闻')).toBeInTheDocument()
    expect(audioInstances[0].src).toBe('')
    expect(audioInstances[1].src).toContain('/api/news/12/tts/?language=original&voice=guy&scope=full')

    await user.click(screen.getByRole('button', { name: '停止语音' }))
    expect(screen.queryByRole('region', { name: '全局语音播放器' })).not.toBeInTheDocument()
    expect(audioInstances[1].src).toBe('')
  })

  it('exposes an accessible range and keeps voice/scope controls on the active article', async () => {
    const user = userEvent.setup()
    renderPlayer()
    await user.click(screen.getByRole('button', { name: '朗读第一篇' }))

    const slider = await screen.findByRole('slider', { name: '播放进度' })
    expect(slider).toHaveAttribute('type', 'range')
    fireEvent.change(slider, { target: { value: '50' } })
    expect(audioInstances[0].currentTime).toBe(60)

    await user.click(screen.getByRole('button', { name: '展开语音设置' }))
    await user.click(screen.getByRole('button', { name: '1.5x' }))
    expect(audioInstances.at(-1).playbackRate).toBe(1.5)

    await user.click(screen.getByRole('button', { name: /晓晓亲切女声/ }))
    expect(audioInstances.at(-1).src).toContain('voice=xiaoxiao')
    expect(audioInstances.at(-1).src).toContain('scope=full')
    await user.click(screen.getByRole('button', { name: '摘要' }))
    expect(audioInstances.at(-1).src).toContain('scope=summary')
    expect(audioInstances.at(-1).src).toContain('/api/news/11/tts/')
  })

  it('ignores a MediaSession play rejection after the active article changes', async () => {
    const user = userEvent.setup()
    renderPlayer()

    await user.click(screen.getByRole('button', { name: '朗读第一篇' }))
    const oldAudio = audioInstances[0]
    oldAudio.pause()
    const oldPlayAction = mediaSession.actionHandlers.get('play')
    const oldPlay = deferred()
    vi.spyOn(oldAudio, 'play').mockReturnValue(oldPlay.promise)
    oldPlayAction()

    await user.click(screen.getByRole('button', { name: '朗读第二篇' }))
    expect(await screen.findByText('第二篇虚构新闻')).toBeInTheDocument()
    expect(screen.getByTestId('player-status')).toHaveTextContent('playing')

    await act(async () => {
      oldPlay.reject(new Error('old track play rejected'))
      await oldPlay.promise.catch(() => {})
    })

    expect(screen.getByTestId('player-status')).toHaveTextContent('playing')
  })

  it('does not restore a stopped player when an old MediaSession play rejects', async () => {
    const user = userEvent.setup()
    renderPlayer()

    await user.click(screen.getByRole('button', { name: '朗读第一篇' }))
    const oldAudio = audioInstances[0]
    oldAudio.pause()
    const oldPlayAction = mediaSession.actionHandlers.get('play')
    const oldPlay = deferred()
    vi.spyOn(oldAudio, 'play').mockReturnValue(oldPlay.promise)
    oldPlayAction()

    await user.click(screen.getByRole('button', { name: '停止语音' }))
    expect(screen.getByTestId('player-status')).toHaveTextContent('idle')

    await act(async () => {
      oldPlay.reject(new Error('stopped track play rejected'))
      await oldPlay.promise.catch(() => {})
    })

    expect(screen.getByTestId('player-status')).toHaveTextContent('idle')
  })
  it('stops and clears viewer A audio when the authenticated viewer changes', async () => {
    const user = userEvent.setup()
    renderPlayer()
    await user.click(screen.getByRole('button', { name: '朗读译文 A' }))
    const privateAudio = audioInstances.at(-1)
    privateAudio.currentTime = 37
    expect(screen.getByTestId('player-status')).toHaveTextContent('playing')

    await user.click(screen.getByRole('button', { name: '切换用户' }))
    expect(privateAudio.src).toBe('')
    expect(screen.getByTestId('player-status')).toHaveTextContent('idle')
    expect(mediaSession.metadata).toBeNull()
    const savedPositionKey = Object.keys(localStorage).find((key) =>
      key.includes('viewer_101') && key.endsWith('11_zh_full_result_41'))
    expect(savedPositionKey).toBeTruthy()
    expect(localStorage.getItem(savedPositionKey)).toContain('"time":37')

    act(() => {
      privateAudio.onplay?.()
      privateAudio.ontimeupdate?.()
      privateAudio.onloadedmetadata?.()
      privateAudio.onended?.()
    })
    expect(screen.getByTestId('player-status')).toHaveTextContent('idle')
    expect(screen.queryByText('译文版本 A')).not.toBeInTheDocument()
  })

  it('invalidates viewer A pending metadata and play promises after an account switch', async () => {
    const user = userEvent.setup()
    renderPlayer()
    deferNextAudioMetadata = true
    await user.click(screen.getByRole('button', { name: '朗读译文 A' }))
    const oldAudio = audioInstances.at(-1)
    expect(screen.getByTestId('player-status')).toHaveTextContent('loading')

    const pendingPlay = deferred()
    vi.spyOn(oldAudio, 'play').mockReturnValue(pendingPlay.promise)
    act(() => oldAudio.onloadedmetadata?.())
    await user.click(screen.getByRole('button', { name: '切换用户' }))
    expect(oldAudio.src).toBe('')
    expect(screen.getByTestId('player-status')).toHaveTextContent('idle')
    expect(mediaSession.metadata).toBeNull()

    await act(async () => {
      pendingPlay.reject(new Error('viewer A play completed after viewer switch'))
      await pendingPlay.promise.catch(() => {})
    })
    expect(screen.getByTestId('player-status')).toHaveTextContent('idle')
    expect(screen.queryByText('译文版本 A')).not.toBeInTheDocument()
  })

  it('keeps explicit saved result identity when replaying and switching versions', async () => {
    const user = userEvent.setup()
    renderPlayer()
    await user.click(screen.getByRole('button', { name: '朗读译文 A' }))
    expect(audioInstances.at(-1).src).toContain('translation_result_id=41')
    await user.click(screen.getByRole('button', { name: '展开语音设置' }))
    await user.click(screen.getByRole('button', { name: /晓晓亲切女声/ }))
    expect(audioInstances.at(-1).src).toContain('translation_result_id=41')
    await user.click(screen.getByRole('button', { name: '朗读译文 B' }))
    expect(audioInstances.at(-1).src).toContain('translation_result_id=42')
    expect(audioInstances.at(-1).src).not.toContain('translation_result_id=41')
  })

})
