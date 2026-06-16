import { useState, useEffect, useRef } from 'react'
import { fetchChatHistory, clearChatHistory, chatStream } from '../services/api'

const ASSISTANT_ERROR = '抱歉，我遇到了一些问题，请稍后再试。'
const SUCCESS_DURATION_MS = 1500

/**
 * Manages chat lifecycle for a given news article + exposes a `phase`
 * state machine so UI (especially the mascot) can react to lifecycle events.
 *
 * Phases:
 *   - 'loading-history' : initial fetch of past messages
 *   - 'idle'            : ready, no active request
 *   - 'thinking'        : user just sent, waiting for first token
 *   - 'streaming'       : tokens arriving
 *   - 'success'         : stream finished, transient (auto-reverts after 1.5s)
 *   - 'error'           : stream failed (sticky until next handleSend)
 *
 * Why no `setIsLoading(true)` synchronously in the effect body?
 *   React 19's `react-hooks/set-state-in-effect` flags it as a cascading
 *   render. We init phase='loading-history' from useState and let the async
 *   load() only ever flip it forward via the async IIFE.
 */
export function useChat(newsId) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [phase, setPhase] = useState('loading-history')
  const [confirmingClear, setConfirmingClear] = useState(false)
  const [webSearch, setWebSearch] = useState(false)
  const successTimerRef = useRef(null)

  // Loading state derived from phase — covers history fetch + active turn
  const isLoading =
    phase === 'loading-history' || phase === 'thinking' || phase === 'streaming'

  useEffect(() => {
    let cancelled = false

    ;(async () => {
      // Reset inside async IIFE so it's not a synchronous effect-body setState
      setMessages([])
      setPhase('loading-history')
      try {
        const data = await fetchChatHistory(newsId)
        if (cancelled) return
        setMessages(data.messages || [])
      } catch (err) {
        if (cancelled) return
        console.error('Failed to load chat history:', err)
      } finally {
        if (!cancelled) setPhase('idle')
      }
    })()

    return () => { cancelled = true }
  }, [newsId])

  // Cleanup success timer on unmount
  useEffect(() => () => clearTimeout(successTimerRef.current), [])

  // Two-step clear flow (replaces native window.confirm):
  //   1) UI calls requestClearChat() → confirmingClear becomes true
  //   2) <ClearChatDialog> renders; user picks confirm or cancel
  //   3) UI calls confirmClear() or cancelClear()
  function requestClearChat() {
    setConfirmingClear(true)
  }

  function cancelClear() {
    setConfirmingClear(false)
  }

  async function confirmClear() {
    setConfirmingClear(false)
    try {
      await clearChatHistory(newsId)
      setMessages([])
    } catch (e) {
      console.error('Failed to clear chat:', e)
    }
  }

  function toggleWebSearch() {
    setWebSearch(prev => !prev)
  }

  async function handleSend() {
    const trimmed = input.trim()
    if (!trimmed || isLoading) return
    doSend(trimmed)
  }

  /** Send an explicit text string — bypasses the input state.
   *  Use when a suggestion click or other caller already has the text
   *  and wants the UI to update immediately without waiting for a re-render. */
  async function doSend(text) {
    if (!text || isLoading) return
    clearTimeout(successTimerRef.current)

    const currentWebSearch = webSearch
    const userMessage = { role: 'user', content: text }
    const assistantMsg = { role: 'assistant', content: '', id: Date.now() }
    if (currentWebSearch) assistantMsg.web_search = true

    setMessages(prev => [...prev, userMessage, assistantMsg])
    setPhase('thinking')

    try {
      let accumulated = ''
      let firstChunk = true
      for await (const chunk of chatStream(newsId, text, { webSearch: currentWebSearch })) {
        if (firstChunk) {
          setPhase('streaming')
          firstChunk = false
        }
        accumulated += chunk
        setMessages(prev => {
          const next = prev.slice()
          next[next.length - 1] = { ...next[next.length - 1], content: accumulated }
          return next
        })
      }
      // Transient success — mascot shows happy mood for 1.5s
      setPhase('success')
      successTimerRef.current = setTimeout(() => setPhase('idle'), SUCCESS_DURATION_MS)
    } catch (err) {
      console.error('Chat error:', err)
      setMessages(prev => {
        const next = prev.slice()
        next[next.length - 1] = { ...next[next.length - 1], content: ASSISTANT_ERROR }
        return next
      })
      setPhase('error')
    }
  }

  return {
    messages, input, setInput,
    isLoading, phase,
    handleSend, doSend,
    confirmingClear, requestClearChat, cancelClear, confirmClear,
    webSearch, toggleWebSearch,
  }
}
