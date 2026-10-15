import { useCallback, useLayoutEffect, useRef } from 'react'
import type { UIEvent, WheelEvent } from 'react'
import type { ChatPhase } from '@/hooks/useChat'
import type { ChatMessage } from '@/services/newsWorkflowApi'

/** Follow replies until the reader scrolls back to an earlier message. */
export function useChatScroll(messages: ChatMessage[], phase: ChatPhase, open: boolean) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const followingRef = useRef(true)
  const previousTopRef = useRef(0)
  const previousUserCountRef = useRef(0)

  const onScroll = useCallback((event: UIEvent<HTMLDivElement>) => {
    const element = event.currentTarget
    if (element.scrollTop < previousTopRef.current - 1) {
      followingRef.current = false
    } else if (element.scrollHeight - element.clientHeight - element.scrollTop <= 48) {
      followingRef.current = true
    }
    previousTopRef.current = element.scrollTop
  }, [])

  const onWheel = useCallback((event: WheelEvent<HTMLDivElement>) => {
    if (event.deltaY < 0) followingRef.current = false
  }, [])

  useLayoutEffect(() => {
    if (!open) {
      followingRef.current = true
      previousUserCountRef.current = 0
      previousTopRef.current = 0
      return
    }
    const userCount = messages.filter(message => message.role === 'user').length
    const sentQuestion = userCount > previousUserCountRef.current && (phase === 'thinking' || phase === 'streaming')
    previousUserCountRef.current = userCount
    if (messages.length === 0 || sentQuestion) followingRef.current = true
    const element = scrollRef.current
    if (!element || !followingRef.current) return
    // Scroll only the conversation, without restarting a smooth animation for
    // every token or moving the article underneath the floating panel.
    element.scrollTop = element.scrollHeight
    previousTopRef.current = element.scrollTop
  }, [messages, open, phase])

  return { scrollRef, onScroll, onWheel }
}
