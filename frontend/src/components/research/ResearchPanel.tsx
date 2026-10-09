import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { LogIn } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/context/AuthContext'
import type { AuthUser } from '@/context/AuthContext'
import { useResearch } from '@/hooks/useResearch'
import AuthModal from '@/components/AuthModal'
import ResearchHeader from './ResearchHeader'
import ResearchMessageList from './ResearchMessageList'
import ResearchInput from './ResearchInput'

interface ResearchPanelProps {
  onClose: () => void
}

const TAB_STOP_SELECTOR = [
  'a[href]',
  'button:not(:disabled)',
  'input:not(:disabled)',
  'textarea:not(:disabled)',
  'select:not(:disabled)',
  '[tabindex]:not([tabindex="-1"])',
].join(', ')

function isUsableTabStop(element: HTMLElement, dialog: HTMLElement) {
  if (!element.isConnected || element.tabIndex < 0) return false
  if (element.matches(':disabled')) return false
  if (element.getAttribute('aria-disabled') === 'true') return false
  if (element.closest('[hidden], [inert], [aria-hidden="true"]')) return false

  let ancestor: HTMLElement | null = element
  while (ancestor) {
    const style = window.getComputedStyle(ancestor)
    if (style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse') return false
    if (ancestor === dialog) break
    ancestor = ancestor.parentElement
  }
  return true
}

function getDialogTabStops(dialog: HTMLElement) {
  return Array.from(dialog.querySelectorAll<HTMLElement>(TAB_STOP_SELECTOR))
    .filter((element) => isUsableTabStop(element, dialog))
}

function focusDialogEdge(dialog: HTMLElement, edge: 'first' | 'last') {
  const tabStops = getDialogTabStops(dialog)
  const orderedStops = edge === 'first' ? tabStops : [...tabStops].reverse()
  for (const tabStop of orderedStops) {
    tabStop.focus()
    if (document.activeElement === tabStop) return
  }
  dialog.focus()
}

export default function ResearchPanel({ onClose }: ResearchPanelProps) {
  const { user } = useAuth()
  return <ResearchPanelView key={user?.id ?? 'anonymous'} user={user} onClose={onClose} />
}

function ResearchPanelView({ user, onClose }: { user: AuthUser | null; onClose: () => void }) {
  const dialogRef = useRef<HTMLDivElement | null>(null)
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
    isBusy,
    recoveryAction,
    handleSend,
    handleNewSession,
    handleSelectSession,
    handleCancel,
    handleResume,
    handleRetry,
  } = useResearch(user?.id ?? null)

  const isLoading = isBusy || phase === 'thinking' || phase === 'tool_calling' || phase === 'streaming'

  const handleClose = useCallback(() => {
    const needsRiskReview = isBusy && !activeSessionId
    handleCancel()
    setIsFullscreen(false)
    if (needsRiskReview) return
    onClose()
  }, [activeSessionId, handleCancel, isBusy, onClose])

  function handleSendQuery() {
    if (!input.trim() || isLoading || hasRecoverableTask || !user) return
    const submittedInput = input
    void handleSend(input.trim(), { localOnly }).then((accepted) => {
      if (accepted) setInput((current) => current === submittedInput ? '' : current)
    })
  }

  function handleSuggestionClick(query: string) {
    if (!user) {
      setShowAuthModal(true)
      return
    }
    if (isBusy || hasRecoverableTask) return
    void handleSend(query, { localOnly: false })
  }

  useLayoutEffect(() => {
    if (showAuthModal) return
    const dialog = dialogRef.current
    const activeElement = document.activeElement
    if (!dialog || (activeElement instanceof HTMLElement && (
      dialog.contains(activeElement) || activeElement.closest('#research-session-menu')
    ))) return
    focusDialogEdge(dialog, 'first')
  })

  useEffect(() => {
    function onFocusIn(event: FocusEvent) {
      if (showAuthModal || document.querySelector('.auth-modal-backdrop')) return
      const dialog = dialogRef.current
      const target = event.target
      if (!dialog || !(target instanceof HTMLElement)) return
      if (dialog.contains(target) || target.closest('#research-session-menu')) return
      focusDialogEdge(dialog, 'first')
    }

    function onKey(event: KeyboardEvent) {
      if (showAuthModal || document.querySelector('.auth-modal-backdrop')) return
      if (event.key === 'Escape' && !event.defaultPrevented) {
        if (isFullscreen) setIsFullscreen(false)
        else handleClose()
        return
      }
      if (event.key !== 'Tab') return

      const dialog = dialogRef.current
      const activeElement = document.activeElement
      if (!dialog) return

      const tabStops = getDialogTabStops(dialog)
      if (!tabStops.length) {
        event.preventDefault()
        dialog.focus()
        return
      }

      const isInsideDialog = activeElement instanceof HTMLElement && dialog.contains(activeElement)
      const isInsideSessionMenu = activeElement instanceof HTMLElement && Boolean(activeElement.closest('#research-session-menu'))
      const first = tabStops[0]
      const last = tabStops[tabStops.length - 1]
      const activeTabStop = activeElement instanceof HTMLElement && tabStops.includes(activeElement)
      if (!isInsideDialog && !isInsideSessionMenu) {
        event.preventDefault()
        focusDialogEdge(dialog, event.shiftKey ? 'last' : 'first')
      } else if (isInsideSessionMenu || !activeTabStop || (event.shiftKey && (activeElement === first || activeElement === dialog))) {
        event.preventDefault()
        focusDialogEdge(dialog, event.shiftKey ? 'last' : 'first')
      } else if (!event.shiftKey && (activeElement === last || activeElement === dialog)) {
        event.preventDefault()
        focusDialogEdge(dialog, 'first')
      }
    }
    document.addEventListener('focusin', onFocusIn)
    window.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('focusin', onFocusIn)
      window.removeEventListener('keydown', onKey)
    }
  }, [isFullscreen, handleClose, showAuthModal])

  useEffect(() => {
    const originalOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    dialogRef.current?.focus()
    return () => { document.body.style.overflow = originalOverflow }
  }, [])

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
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="新闻研究助手"
        tabIndex={-1}
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
                disabled={isBusy}
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
                  <span>原请求可能已到达服务器。只有点击下方按钮才会新建任务，可能重复计算或产生费用。</span>
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
