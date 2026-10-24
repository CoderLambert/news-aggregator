import { contentCompletenessLabel } from '@/lib/contentCompleteness'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useChat, type ChatPhase } from '@/hooks/useChat'
import { useSuggestedQuestions } from '@/hooks/useSuggestedQuestions'
import { useChatScroll } from '@/hooks/useChatScroll'
import ChatBubbleButton from '@/components/chat/ChatBubbleButton'
import ChatHeader from '@/components/chat/ChatHeader'
import ChatMessageList from '@/components/chat/ChatMessageList'
import ChatInput from '@/components/chat/ChatInput'
import { useDefaultAIModel } from '@/hooks/useDefaultAIModel'
import { useAuth } from '@/context/AuthContext'
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

interface NewsChatAssistantProps {
  newsId: string | number
  open?: boolean
  onOpenChange?: (open: boolean) => void
  translationResultId?: number | null
  translationMode?: 'current' | 'original' | 'result'
  translationLabel?: string
  articleContext?: {
    hasFullContent?: boolean
    completeness?: 'unknown' | 'summary' | 'verified'
    wordCount?: number
    contentRevision?: number
    title?: string
    isMedical?: boolean
    sourceUrl?: string
  }
}

export default function NewsChatAssistant({ newsId, open, onOpenChange, translationResultId, translationMode, translationLabel, articleContext }: NewsChatAssistantProps) {
  const resolvedTranslationMode = translationMode ?? (translationResultId != null ? 'result' : 'current')
  const { user } = useAuth()
  const [internalOpen, setInternalOpen] = useState(false)
  const isOpen = open ?? internalOpen
  const defaultModel = useDefaultAIModel(user?.id ?? null, 'article_qa', isOpen)
  const selectedSource = defaultModel.selection?.selection_source ?? null
  const selectedModelId = selectedSource === 'byok'
    ? defaultModel.selection?.model_config_id ?? null : null
  const hasExecutionSource = selectedSource === 'chatgpt_subscription' || Boolean(selectedModelId)
  const defaultUnavailable = Boolean(user && (!hasExecutionSource || defaultModel.isPending || defaultModel.isError))
  const setIsOpen = useCallback((nextOpen: boolean) => {
    if (open === undefined) setInternalOpen(nextOpen)
    onOpenChange?.(nextOpen)
  }, [onOpenChange, open])
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [confettiFired, setConfettiFired] = useState(false)
  const hasCelebratedRef = useRef(false)
  const bubbleTriggerRef = useRef<HTMLButtonElement | null>(null)
  const restoreBubbleFocusRef = useRef(false)
  const {
    messages, input, setInput, isLoading, phase,
    historyError, retryHistory,
    handleSend, doSend, stopWaiting,
    confirmingClear, isClearing, clearError, requestClearChat, cancelClear, confirmClear,
    uncertainTurn, checkPendingTurn, resendUncertainTurn,
    webSearch, toggleWebSearch,
  } = useChat(newsId, isOpen, selectedModelId, Boolean(selectedModelId && !defaultUnavailable), translationResultId, resolvedTranslationMode)
  const { scrollRef: chatScrollRef, onScroll: onChatScroll, onWheel: onChatWheel } = useChatScroll(messages, phase, isOpen)
  const submitChatTurn = (send: () => Promise<boolean>) => {
    if (defaultUnavailable) return
    // Only an explicit send or suggested-question click calls this path.
    // Reading preferences/history never submits inference.
    void send()
  }

  const {
    questions: suggestedQuestions,
    contextScope: suggestionContextScope,
    generated: suggestionsGenerated,
    loading: refreshingSuggestions,
    refresh: refreshSuggestions,
    error: suggestionError,
    modelConfigId: suggestionModelId,
    selectionSource: suggestionSource,
  } = useSuggestedQuestions(newsId, isOpen, articleContext?.contentRevision ?? 0)

  const canGenerateSuggestions = !user || suggestionSource === 'chatgpt_subscription' || Boolean(suggestionModelId)
  const generateSuggestions = () => {
    if (!canGenerateSuggestions) return
    // Clicking generate/refresh is the explicit authorization for this request.
    void refreshSuggestions(true)
  }

  useEffect(() => {
    if (phase === 'success' && !hasCelebratedRef.current) {
      hasCelebratedRef.current = true
      setConfettiFired(true)
      const timer = setTimeout(() => setConfettiFired(false), 2500)
      return () => clearTimeout(timer)
    }
  }, [phase])

  const openFromBubble = useCallback(() => {
    restoreBubbleFocusRef.current = true
    setIsOpen(true)
  }, [setIsOpen])

  const closePanel = useCallback(() => {
    stopWaiting()
    setIsOpen(false)
    const shouldRestoreBubbleFocus = restoreBubbleFocusRef.current
    restoreBubbleFocusRef.current = false
    if (shouldRestoreBubbleFocus) {
      requestAnimationFrame(() => bubbleTriggerRef.current?.focus())
    }
  }, [setIsOpen, stopWaiting])

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
    // Only lock scroll on small screens; keep desktop scrollable for side-by-side reading
    if (typeof window !== 'undefined' && window.innerWidth < 1024) {
      const original = document.body.style.overflow
      document.body.style.overflow = 'hidden'
      return () => { document.body.style.overflow = original }
    }
  }, [isOpen])

  if (!isOpen) return <ChatBubbleButton buttonRef={bubbleTriggerRef} onOpen={openFromBubble} />

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="AI 助手小闻"
      className={`pointer-events-none fixed inset-0 z-50 flex flex-col ${
        isFullscreen ? 'items-center justify-center bg-background' : 'justify-end lg:items-end lg:justify-end lg:p-6'
      }`}
    >
      {!isFullscreen && (
        <div
          className="pointer-events-auto absolute inset-0 bg-black/10 backdrop-blur-xs lg:hidden transition-opacity"
          onClick={closePanel}
          aria-hidden="true"
        />
      )}

      <div
        className={`news-chat-panel pointer-events-auto relative flex flex-col overflow-hidden border border-border bg-card text-card-foreground shadow-2xl transition-all ${
          isFullscreen
            ? 'h-full w-full rounded-none md:h-[min(92dvh,980px)] md:w-[min(94vw,1600px)] md:rounded-2xl'
            : 'h-[85dvh] w-full rounded-t-3xl sm:h-[min(78dvh,720px)] sm:w-[480px] sm:rounded-2xl'
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
        {user && defaultUnavailable && <section aria-label="问答状态" className="border-b border-border px-4 py-2 text-xs md:px-6" role="status">
          <p>{defaultModel.isPending ? '正在准备小闻…' : defaultModel.isError
            ? '暂时无法读取默认模型，请重试。' : '小闻暂不可用。'}
            {defaultModel.isError && <Button type="button" variant="link" size="sm" onClick={() => void defaultModel.refetch()}>重新读取</Button>}</p>
        </section>}

        {/* Context Status Banner */}
        <div className="flex items-center justify-between border-b border-border bg-secondary/60 px-4 py-2 text-[11px] md:px-6 md:text-xs">
          <div className="flex items-center gap-1.5 font-medium">
            <span className={`size-2 rounded-full ${articleContext?.completeness === 'verified' ? 'bg-emerald-500' : 'bg-amber-400'}`} />
            <span className={articleContext?.completeness === 'verified' ? 'text-emerald-800 dark:text-emerald-300' : 'text-amber-800 dark:text-amber-300'}>
              {contentCompletenessLabel(Boolean(articleContext?.hasFullContent), articleContext?.completeness)}
            </span>
          </div>
          {suggestedQuestions.length > 0 && (
            <Button
              type="button" variant="ghost" size="sm"
              onClick={generateSuggestions}
              disabled={refreshingSuggestions || !canGenerateSuggestions}
              className="text-muted-foreground hover:text-foreground text-[10px]"
            >
              {suggestionsGenerated ? '换一批建议' : '生成推荐问题'}
            </Button>
          )}
        </div>

        {suggestionError && <p role="alert" className="px-4 py-1 text-xs text-destructive">推荐问题生成失败，未自动重试。仍可使用现有问题或免费模板。</p>}
        <div ref={chatScrollRef} onScroll={onChatScroll} onWheel={onChatWheel} className="chat-panel-scroll min-h-0 flex-1 space-y-3 overflow-y-auto overscroll-contain bg-background/55 p-4 sm:p-5 md:p-7">
          {historyError && (
            <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900/60 dark:bg-red-950/35 dark:text-red-200">
              聊天记录加载失败。<button type="button" className="ml-1 underline" onClick={() => void retryHistory()}>重试</button>
            </div>
          )}
          {uncertainTurn && (
            <div role="alert" className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/35 dark:text-amber-200">
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
          {translationLabel && <p className="mb-2 rounded-md border border-border bg-muted/40 px-3 py-2 text-xs text-muted-foreground" role="status">当前对话：{translationLabel}</p>}
          <ChatMessageList
            messages={messages}
            medicalSourceUrl={articleContext?.isMedical ? articleContext.sourceUrl : undefined}
            phase={phase}
            onSuggestionClick={(text: string) => submitChatTurn(() => doSend(text))}
            suggestedQuestions={suggestedQuestions}
            suggestionContextScope={suggestionContextScope}
            suggestionsGenerated={suggestionsGenerated}
            onRefreshSuggestions={canGenerateSuggestions ? generateSuggestions : undefined}
            refreshingSuggestions={refreshingSuggestions}
          />
        </div>

        <ChatInput
          value={input}
          onChange={setInput}
          onSend={() => submitChatTurn(handleSend)}
          onStop={phase === 'thinking' || phase === 'streaming' ? stopWaiting : undefined}
          isLoading={isLoading}
          sendDisabled={defaultUnavailable || Boolean(uncertainTurn) || confirmingClear}
          disabled={confirmingClear || isClearing}
          autoFocus={isOpen}
          webSearch={selectedModelId ? false : webSearch}
          onWebSearchToggle={selectedModelId ? undefined : toggleWebSearch}
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
