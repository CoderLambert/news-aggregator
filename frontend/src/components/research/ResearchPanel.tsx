import { useEffect, useState } from 'react'
import { LogIn } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/context/AuthContext'
import type { AuthUser } from '@/context/AuthContext'
import { useResearch } from '@/hooks/useResearch'
import AuthModal from '@/components/AuthModal'
import ResearchBubbleButton from './ResearchBubbleButton'
import ResearchHeader from './ResearchHeader'
import ResearchMessageList from './ResearchMessageList'
import ResearchInput from './ResearchInput'

export default function ResearchPanel() {
  const { user } = useAuth()
  return <ResearchPanelView key={user?.id ?? 'anonymous'} user={user} />
}

function ResearchPanelView({ user }: { user: AuthUser | null }) {
  const [isOpen, setIsOpen] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [showAuthModal, setShowAuthModal] = useState(false)
  const [input, setInput] = useState('')
  const [localOnly, setLocalOnly] = useState(false)
  const {
    sessions,
    activeSessionId,
    messages,
    phase,
    searchResults,
    hasRecoverableTask,
    recoveryAction,
    handleSend,
    handleNewSession,
    handleSelectSession,
    handleCancel,
    handleResume,
    handleRetry,
  } = useResearch(user?.id ?? null)

  const isLoading = phase === 'thinking' || phase === 'tool_calling' || phase === 'streaming'

  function handleOpen() {
    setIsOpen(true)
  }

  function handleClose() {
    setIsOpen(false)
    setIsFullscreen(false)
  }

  function handleSendQuery() {
    if (!input.trim() || isLoading || hasRecoverableTask || !user) return
    void handleSend(input.trim(), { localOnly })
    setInput('')
  }

  function handleSuggestionClick(query: string) {
    if (!user) {
      setShowAuthModal(true)
      return
    }
    if (hasRecoverableTask) return
    void handleSend(query, { localOnly: false })
  }

  useEffect(() => {
    if (!isOpen) return
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        if (isFullscreen) setIsFullscreen(false)
        else setIsOpen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [isOpen, isFullscreen])

  useEffect(() => {
    if (!isOpen) return
    const originalOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = originalOverflow }
  }, [isOpen])

  if (!isOpen) return <ResearchBubbleButton onOpen={handleOpen} />

  const activeSession = sessions.find((session) => session.id === activeSessionId)
  const panelTitle = activeSession?.title || '新闻研究'

  return (
    <>
      {!isFullscreen && (
        <div
          className="fixed inset-0 z-30 bg-black/10 backdrop-blur-sm transition-opacity pointer-events-auto"
          onClick={handleClose}
          aria-hidden="true"
        />
      )}

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
          onToggleFullscreen={() => setIsFullscreen((fullscreen) => !fullscreen)}
          onNewSession={handleNewSession}
          onClose={handleClose}
          sessions={sessions}
          activeSessionId={activeSessionId}
          onSelectSession={handleSelectSession}
        />

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
              <Button type="button" className="mt-5 rounded-full" onClick={() => setShowAuthModal(true)}>
                登录 / 注册
              </Button>
            </div>
          ) : (
            <>
              <ResearchMessageList
                messages={messages}
                phase={phase}
                searchResults={searchResults}
                onSuggestionClick={handleSuggestionClick}
              />
              {recoveryAction === 'resume' && (
                <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-100 bg-amber-50 p-3 text-xs text-amber-800">
                  <span>浏览器连接已停止；后台任务可能仍在执行。重新连接会回放当前任务的事件。</span>
                  <Button type="button" size="sm" variant="outline" onClick={() => void handleResume()}>
                    继续接收
                  </Button>
                </div>
              )}
              {recoveryAction === 'retry' && (
                <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-100 bg-rose-50 p-3 text-xs text-rose-800">
                  <span>当前研究没有完成。重新研究会发起一项新的服务端任务。</span>
                  <Button type="button" size="sm" variant="outline" onClick={() => void handleRetry()}>
                    重新研究
                  </Button>
                </div>
              )}
            </>
          )}
        </div>

        <ResearchInput
          value={input}
          onChange={setInput}
          onSend={user ? handleSendQuery : () => setShowAuthModal(true)}
          onCancel={handleCancel}
          isLoading={isLoading}
          disabled={!user || hasRecoverableTask}
          localOnly={localOnly}
          onToggleLocalOnly={() => setLocalOnly((enabled) => !enabled)}
        />
      </div>

      {showAuthModal && <AuthModal onClose={() => setShowAuthModal(false)} />}
    </>
  )
}
