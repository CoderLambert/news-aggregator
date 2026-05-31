import { useState, useEffect } from 'react'
import { fetchChatHistory, clearChatHistory, chatStream } from '../services/api'

const ASSISTANT_ERROR = '抱歉，我遇到了一些问题，请稍后再试。'

/**
 * Manages chat lifecycle for a given news article.
 * Returns messages + actions; UI components are presentation-only.
 */
export function useChat(newsId) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  // Load history when article changes
  useEffect(() => {
    let cancelled = false
    setMessages([])
    setIsLoading(true)
    fetchChatHistory(newsId)
      .then(data => { if (!cancelled) setMessages(data.messages || []) })
      .catch(err => console.error('Failed to load chat history:', err))
      .finally(() => { if (!cancelled) setIsLoading(false) })
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
        // Replace last (assistant) message with incremental content
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
