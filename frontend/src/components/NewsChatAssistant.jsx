import { useState, useEffect, useRef } from 'react'
import 'markstream-react/index.css'
import { useChat } from '../hooks/useChat'
import { useSuggestedQuestions } from '../hooks/useSuggestedQuestions'
import ChatBubbleButton from './chat/ChatBubbleButton'
import ChatHeader from './chat/ChatHeader'
import ChatMessageList from './chat/ChatMessageList'
import ChatInput from './chat/ChatInput'
import ClearChatDialog from './chat/ClearChatDialog'
import Confetti from './chat/Confetti'

/**
 * AI 新闻助手「小闻」— floating panel anchored to bottom-right.
 * Streams chat from /api/news/:id/chat/ via chatStream helper.
 *
 * Phase → Mascot mood mapping centralizes the "personality" logic.
 */
function phaseToMood(phase) {
  switch (phase) {
    case 'thinking':  return 'think'
    case 'streaming': return 'talk'
    case 'success':   return 'happy'
    case 'error':     return 'confused'
    default:          return 'idle'
  }
}

export default function NewsChatAssistant({ newsId }) {
  const [isOpen, setIsOpen] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [confettiFired, setConfettiFired] = useState(false)
  // Tracks whether this user has already celebrated once this page-load.
  // We fire confetti on the FIRST transition into 'success' only — subsequent
  // successes are still happy but no more paper bits (would feel spammy).
  const hasCelebratedRef = useRef(false)
  const {
    messages, input, setInput, isLoading, phase,
    handleSend,
    confirmingClear, requestClearChat, cancelClear, confirmClear,
  } = useChat(newsId)

  // Only fetch LLM suggestions once the user actually opens the panel,
  // to avoid burning tokens for readers who never chat.
  const { questions: suggestedQuestions } = useSuggestedQuestions(newsId, isOpen)

  // Fire confetti exactly once when phase first hits 'success'
  useEffect(() => {
    if (phase === 'success' && !hasCelebratedRef.current) {
      hasCelebratedRef.current = true
      setConfettiFired(true)
      // Confetti component self-resets via its own timer; reset our trigger
      // shortly after so a re-mount wouldn't re-fire (defensive).
      const t = setTimeout(() => setConfettiFired(false), 2500)
      return () => clearTimeout(t)
    }
  }, [phase])

  // ESC closes the panel (but defers to ClearChatDialog when it's open)
  useEffect(() => {
    if (!isOpen) return
    function onKey(e) {
      if (e.key === 'Escape') {
        if (confirmingClear) return // let the dialog handle Esc
        if (isFullscreen) setIsFullscreen(false)
        else setIsOpen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [isOpen, isFullscreen, confirmingClear])

  if (!isOpen) {
    return <ChatBubbleButton onOpen={() => setIsOpen(true)} />
  }

  const mood = phaseToMood(phase)

  // Suggested-question click: drop into input then send next tick
  function handleSuggestionClick(text) {
    setInput(text)
    // Defer to next microtask so the input state is committed before send reads it
    Promise.resolve().then(() => handleSend())
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="AI 助手小闻"
      className={`fixed inset-0 z-50 flex flex-col ${
        isFullscreen ? 'justify-center items-center bg-white' : 'justify-end sm:justify-center sm:items-center'
      } pointer-events-none`}
    >
      {/* Backdrop */}
      {!isFullscreen && (
        <div
          className="absolute inset-0 bg-black/20 backdrop-blur-sm pointer-events-auto transition-opacity"
          onClick={() => setIsOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Window */}
      <div
        className={`relative ${
          isFullscreen
            ? 'w-full h-full sm:w-[480px] sm:h-[90vh] sm:rounded-2xl'
            : 'w-full h-[85vh] sm:h-[600px] sm:w-[450px] rounded-t-3xl sm:rounded-2xl'
        } bg-white shadow-2xl pointer-events-auto flex flex-col overflow-hidden`}
      >
        <ChatHeader
          mood={mood}
          isFullscreen={isFullscreen}
          onToggleFullscreen={() => setIsFullscreen(f => !f)}
          onClear={requestClearChat}
          onClose={() => setIsOpen(false)}
        />

        <div className="flex-1 overflow-y-auto p-3 sm:p-4 space-y-4 bg-gradient-to-b from-orange-50/30 to-white">
          <ChatMessageList
            messages={messages}
            phase={phase}
            onSuggestionClick={handleSuggestionClick}
            suggestedQuestions={suggestedQuestions}
          />
        </div>

        <ChatInput
          value={input}
          onChange={setInput}
          onSend={handleSend}
          isLoading={isLoading}
          autoFocus={isOpen}
        />

        {/* Confetti overlay — fires once on first successful answer */}
        <Confetti fire={confettiFired} />
      </div>

      <ClearChatDialog
        open={confirmingClear}
        onConfirm={confirmClear}
        onCancel={cancelClear}
      />
    </div>
  )
}
