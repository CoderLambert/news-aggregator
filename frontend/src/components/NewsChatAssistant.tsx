import { useCallback, useEffect, useRef, useState } from 'react'
import { useChat, type ChatPhase } from '@/hooks/useChat'
import { useSuggestedQuestions } from '@/hooks/useSuggestedQuestions'
import ChatBubbleButton from '@/components/chat/ChatBubbleButton'
import ChatHeader from '@/components/chat/ChatHeader'
import ChatMessageList from '@/components/chat/ChatMessageList'
import ChatInput from '@/components/chat/ChatInput'
import ClearChatDialog from '@/components/chat/ClearChatDialog'
import Confetti from '@/components/chat/Confetti'
import { Button } from '@/components/ui/button'

function phaseToMood(phase: ChatPhase): string {
  switch (phase) {
    case 'thinking': return 'think'
    case 'streaming': return 'talk'
    case 'success': return 'happy'
    case 'error': return 'confused'
    default: return 'idle'
  }
}

export default function NewsChatAssistant({ newsId }: { newsId: string | number }) {
  const [isOpen, setIsOpen] = useState(false)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [confettiFired, setConfettiFired] = useState(false)
  const hasCelebratedRef = useRef(false)
  const {
    messages, input, setInput, isLoading, phase,
    historyError, retryHistory,
    handleSend, doSend, stopWaiting,
    confirmingClear, isClearing, clearError, requestClearChat, cancelClear, confirmClear,
    uncertainTurn, checkPendingTurn, resendUncertainTurn,
    webSearch, toggleWebSearch,
  } = useChat(newsId, isOpen)

  const {
    questions: suggestedQuestions,
    loading: refreshingSuggestions,
    refresh: refreshSuggestions,
  } = useSuggestedQuestions(newsId, isOpen)

  useEffect(() => {
    if (phase === 'success' && !hasCelebratedRef.current) {
      hasCelebratedRef.current = true
      setConfettiFired(true)
      const timer = setTimeout(() => setConfettiFired(false), 2500)
      return () => clearTimeout(timer)
    }
  }, [phase])

  const closePanel = useCallback(() => {
    stopWaiting()
    setIsOpen(false)
  }, [stopWaiting])

  useEffect(() => {
    if (!isOpen) return
    function onKey(event: KeyboardEvent) {
      if (event.key !== 'Escape' || confirmingClear) return
      if (isFullscreen) setIsFullscreen(false)
      else closePanel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [closePanel, confirmingClear, isFullscreen, isOpen])

  useEffect(() => {
    if (!isOpen) return
    const original = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = original }
  }, [isOpen])

  if (!isOpen) return <ChatBubbleButton onOpen={() => setIsOpen(true)} />

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="AI 助手小闻"
      className={`pointer-events-none fixed inset-0 z-50 flex flex-col ${
        isFullscreen ? 'items-center justify-center bg-white' : 'justify-end sm:items-center sm:justify-center'
      }`}
    >
      {!isFullscreen && (
        <div
          className="pointer-events-auto absolute inset-0 bg-black/20 backdrop-blur-sm transition-opacity"
          onClick={closePanel}
          aria-hidden="true"
        />
      )}

      <div
        className={`pointer-events-auto relative flex flex-col overflow-hidden bg-white shadow-2xl ${
          isFullscreen
            ? 'h-full w-full sm:h-[90vh] sm:w-[480px] sm:rounded-2xl'
            : 'h-[85vh] w-full rounded-t-3xl sm:h-[600px] sm:w-[450px] sm:rounded-2xl'
        }`}
      >
        <ChatHeader
          mood={phaseToMood(phase)}
          isFullscreen={isFullscreen}
          onToggleFullscreen={() => setIsFullscreen((current) => !current)}
          onClear={requestClearChat}
          clearDisabled={confirmingClear}
          onClose={closePanel}
        />

        <div className="flex-1 space-y-4 overflow-y-auto overscroll-contain bg-gradient-to-b from-orange-50/30 to-white p-3 sm:p-4">
          {historyError && (
            <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              聊天记录加载失败。<button type="button" className="ml-1 underline" onClick={() => void retryHistory()}>重试</button>
            </div>
          )}
          {uncertainTurn && (
            <div role="alert" className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
              <p className="font-medium">
                {uncertainTurn.reconciliation === 'checking'
                  ? '正在只读核对服务器记录…'
                  : uncertainTurn.reconciliation === 'partial'
                    ? '服务器已保存这条问题，但暂未找到已保存的回答。为避免重复提交，此问题暂不可重发。'
                    : '无法确认服务器是否已处理这条问题。草稿已保留；显式重发可能创建重复请求并产生额外费用。'}
              </p>
              {uncertainTurn.reconciliation !== 'partial' && (
                <p className="mt-1 text-xs">
                  {uncertainTurn.reconciliation === 'failed'
                    ? '核对记录失败。你可以重新检查，或在确认风险后显式重发。'
                    : '系统不会自动重发。'}
                </p>
              )}
              <div className="mt-2 flex flex-wrap gap-2">
                {uncertainTurn.reconciliation !== 'checking' && (
                  <Button type="button" size="sm" variant="outline" onClick={() => { void checkPendingTurn() }}>
                    重新检查记录
                  </Button>
                )}
                {!uncertainTurn.serverQuestionSaved && uncertainTurn.reconciliation !== 'checking' && (
                  <Button type="button" size="sm" variant="destructive" onClick={() => { void resendUncertainTurn() }}>
                    仍要重发（可能重复/计费）
                  </Button>
                )}
              </div>
            </div>
          )}
          <ChatMessageList
            messages={messages}
            phase={phase}
            onSuggestionClick={(text: string) => { void doSend(text) }}
            suggestedQuestions={suggestedQuestions}
            onRefreshSuggestions={() => { void refreshSuggestions() }}
            refreshingSuggestions={refreshingSuggestions}
          />
        </div>

        <ChatInput
          value={input}
          onChange={setInput}
          onSend={() => { void handleSend() }}
          onStop={phase === 'thinking' || phase === 'streaming' ? stopWaiting : undefined}
          isLoading={isLoading}
          sendDisabled={Boolean(uncertainTurn) || confirmingClear}
          disabled={confirmingClear || isClearing}
          autoFocus={isOpen}
          webSearch={webSearch}
          onWebSearchToggle={toggleWebSearch}
        />

        <Confetti fire={confettiFired} />
      </div>

      <ClearChatDialog
        open={confirmingClear}
        isClearing={isClearing}
        error={clearError}
        onConfirm={() => { void confirmClear() }}
        onCancel={cancelClear}
      />
    </div>
  )
}
