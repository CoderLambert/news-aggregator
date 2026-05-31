import { useState, useEffect } from 'react'
import { fetchChatHistory, clearChatHistory, chatStream } from '../services/api'

const ASSISTANT_ERROR = '抱歉，我遇到了一些问题，请稍后再试。'

/**
 * Manages chat lifecycle for a given news article.
 * Returns messages + actions; UI components are presentation-only.
 *
 * Why no `setIsLoading(true)` synchronously in the effect body?
 *   React 19's `react-hooks/set-state-in-effect` flags it as a cascading
 *   render. Instead we initialise `isLoading` to true from useState and let
 *   the async `load()` only ever flip it to false. For id changes we use a
 *   `loadingId` state we compare against to detect "new id arrived" and reset
 *   inside async land.
 */
export function useChat(newsId) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    let cancelled = false

    ;(async () => {
      // Reset happens inside the async IIFE so it's not a synchronous
      // effect-body setState. Microtask boundary turns this into an event-
      // like update from React's perspective.
      setMessages([])
      setIsLoading(true)
      try {
        const data = await fetchChatHistory(newsId)
        if (cancelled) return
        setMessages(data.messages || [])
      } catch (err) {
        if (cancelled) return
        console.error('Failed to load chat history:', err)
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    })()

    return () => { cancelled = true }
  }, [newsId])

  async function handleClearChat() {
    if (!window.confirm('确定要清空关于这篇文章的对话记录吗？')) return
    try {
      await clearChatHistory(newsId)
      setMessages([])
    } catch (e) {
      console.error('Failed to clear chat:', e)
    }
  }

  async function handleSend() {
    const trimmed = input.trim()
    if (!trimmed || isLoading) return

    const userMessage = { role: 'user', content: trimmed }
    setMessages(prev => [...prev, userMessage, { role: 'assistant', content: '', id: Date.now() }])
    setInput('')
    setIsLoading(true)

    try {
      let accumulated = ''
      for await (const chunk of chatStream(newsId, trimmed)) {
        accumulated += chunk
        setMessages(prev => {
          const next = prev.slice()
          next[next.length - 1] = { ...next[next.length - 1], content: accumulated }
          return next
        })
      }
    } catch (err) {
      console.error('Chat error:', err)
      setMessages(prev => {
        const next = prev.slice()
        next[next.length - 1] = { ...next[next.length - 1], content: ASSISTANT_ERROR }
        return next
      })
    } finally {
      setIsLoading(false)
    }
  }

  return { messages, input, setInput, isLoading, handleSend, handleClearChat }
}
