import { useState, useEffect } from 'react'
import 'markstream-react/index.css'
import { useChat } from '../hooks/useChat'
import ChatBubbleButton from './chat/ChatBubbleButton'
import ChatHeader from './chat/ChatHeader'
import ChatMessageList from './chat/ChatMessageList'
import ChatInput from './chat/ChatInput'

/**
 * AI 新闻助手 — floating panel anchored to bottom-right. Streams chat from
 * /api/news/:id/chat/ via the chatStream helper (services/api.js).
 */
export default function NewsChatAssistant({ newsId }) {
  const [isOpen, setIsOpen] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const {
    messages, input, setInput, isLoading,
    handleSend, handleClearChat,
  } = useChat(newsId)

  // ESC closes the panel
  useEffect(() => {
    if (!isOpen) return
    function onKey(e) {
      if (e.key === 'Escape') {
        if (isFullscreen) setIsFullscreen(false)
        else setIsOpen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [isOpen, isFullscreen])

  if (!isOpen) {
    return <ChatBubbleButton onOpen={() => setIsOpen(true)} />
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="AI 新闻助手"
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
            : 'w-full h-[85vh] sm:h-[600px] sm:w-[450px]'
        } bg-white shadow-2xl pointer-events-auto flex flex-col overflow-hidden animate-slide-up sm:animate-fade-in`}
      >
        <ChatHeader
          isFullscreen={isFullscreen}
          onToggleFullscreen={() => setIsFullscreen(f => !f)}
          onClear={handleClearChat}
          onClose={() => setIsOpen(false)}
        />

        <div className="flex-1 overflow-y-auto p-2 sm:p-4 space-y-4 bg-gray-50/50">
          <ChatMessageList messages={messages} isLoading={isLoading} />
        </div>

        <ChatInput
          value={input}
          onChange={setInput}
          onSend={handleSend}
          isLoading={isLoading}
          autoFocus={isOpen}
        />
      </div>
    </div>
  )
}
