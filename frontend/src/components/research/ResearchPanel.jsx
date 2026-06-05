import { useState, useEffect } from 'react'
import { useResearch } from '../../hooks/useResearch'
import { useAuth } from '../../context/AuthContext'
import AuthModal from '../AuthModal'
import ResearchBubbleButton from './ResearchBubbleButton'
import ResearchHeader from './ResearchHeader'
import ResearchMessageList from './ResearchMessageList'
import ResearchInput from './ResearchInput'
import { LogIn } from 'lucide-react'

/**
 * Research Agent panel — floating panel with backdrop blur,
 * accessible from any page. Clean, modern design.
 */
export default function ResearchPanel() {
  const [isOpen, setIsOpen] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [showAuthModal, setShowAuthModal] = useState(false)
  const [input, setInput] = useState('')
  const { user } = useAuth()

  const {
    sessions,
    activeSessionId,
    messages,
    phase,
    searchResults,
    handleSend,
    handleNewSession,
    handleSelectSession,
  } = useResearch()

  const isLoading = phase === 'thinking' || phase === 'tool_calling' || phase === 'streaming'

  function handleOpen() {
    setIsOpen(true)
  }

  function handleClose() {
    setIsOpen(false)
    setIsFullscreen(false)
  }

  function handleSendQuery() {
    if (!input.trim() || isLoading) return
    handleSend(input.trim())
    setInput('')
  }

  function handleSuggestionClick(text) {
    if (!user) {
      setShowAuthModal(true)
      return
    }
    handleSend(text)
  }

  // ESC key to close
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

  // Lock body scroll when panel is open — prevents the main page
  // from scrolling when the user swipes inside the panel on mobile.
  useEffect(() => {
    if (!isOpen) return
    const original = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = original }
  }, [isOpen])

  if (!isOpen) {
    return <ResearchBubbleButton onOpen={handleOpen} />
  }

  const activeSession = sessions.find(s => s.id === activeSessionId)
  const panelTitle = activeSession?.title || '新闻研究'

  return (
    <>
      {/* Backdrop overlay */}
      {!isFullscreen && (
        <div
          className="fixed inset-0 z-30 bg-black/10 backdrop-blur-sm transition-opacity pointer-events-auto"
          onClick={handleClose}
          aria-hidden="true"
        />
      )}

      {/* Panel */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label="新闻研究助手"
        className={`fixed z-40 flex flex-col bg-white rounded-t-2xl sm:rounded-2xl shadow-[0_-8px_32px_-8px_rgba(0,0,0,0.12)]
          border border-neutral-200/50 overflow-hidden
          transition-all duration-300 ease-out pointer-events-auto
          ${isFullscreen
            ? 'inset-2 rounded-2xl'
            : 'bottom-[60px] right-0 sm:right-6 w-[600px] h-[720px] max-[640px]:inset-x-0 max-[640px]:bottom-0 max-[640px]:w-auto max-[640px]:h-[85vh]'
          }`}
      >
        <ResearchHeader
          title={panelTitle}
          phase={phase}
          isFullscreen={isFullscreen}
          onToggleFullscreen={() => setIsFullscreen(!isFullscreen)}
          onNewSession={handleNewSession}
          onClose={handleClose}
          sessions={sessions}
          activeSessionId={activeSessionId}
          onSelectSession={handleSelectSession}
        />

        {/* Message area */}
        <div className="flex-1 overflow-y-auto overscroll-contain px-4 py-3 space-y-3 bg-gradient-to-b from-violet-50/30 via-neutral-50/30 to-white">
          {!user ? (
            <div className="flex flex-col items-center justify-center h-full text-center px-6">
              <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-violet-100 to-orange-50 flex items-center justify-center shadow-lg shadow-violet-100/50 mb-4">
                <LogIn className="w-7 h-7 text-violet-500" />
              </div>
              <p className="text-base font-bold text-neutral-900">需要登录</p>
              <p className="mt-1.5 text-xs text-neutral-400 max-w-[260px] leading-relaxed">
                研究助手需要登录后才能使用，登录即可开始深度新闻分析
              </p>
              <button
                type="button"
                onClick={() => setShowAuthModal(true)}
                className="mt-5 px-6 py-2.5 rounded-full bg-gradient-to-br from-violet-500 to-violet-600
                           text-white text-sm font-semibold shadow-md shadow-violet-200/50
                           hover:shadow-lg hover:shadow-violet-300/50 hover:scale-105
                           active:scale-95 transition-all"
              >
                登录 / 注册
              </button>
            </div>
          ) : (
            <ResearchMessageList
              messages={messages}
              phase={phase}
              searchResults={searchResults}
              onSuggestionClick={handleSuggestionClick}
            />
          )}
        </div>

        {/* Input area */}
        <ResearchInput
          value={input}
          onChange={setInput}
          onSend={user ? handleSendQuery : () => setShowAuthModal(true)}
          isLoading={isLoading}
          disabled={!user}
        />
      </div>

      {/* Auth modal */}
      {showAuthModal && (
        <AuthModal onClose={() => setShowAuthModal(false)} />
      )}
    </>
  )
}
