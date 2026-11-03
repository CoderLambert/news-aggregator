import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { LogIn } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { useAuth } from '@/context/AuthContext'
import type { AuthUser } from '@/context/AuthContext'
import { useResearch } from '@/hooks/useResearch'
import AuthModal from '@/components/AuthModal'
import ResearchHeader from './ResearchHeader'
import ResearchMessageList from './ResearchMessageList'
import ResearchInput from './ResearchInput'
import { listAITaskPreferences } from '@/services/aiConnectionsApi'
import type { ResearchCreateAuthorization } from '@/services/researchApi'

interface ResearchPanelProps {
  onClose: () => void
  authorizedCreateOnly?: boolean
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

export default function ResearchPanel({ onClose, authorizedCreateOnly = false }: ResearchPanelProps) {
  const { user } = useAuth()
  return (
    <ResearchPanelView
      key={user?.id ?? 'anonymous'}
      user={user}
      onClose={onClose}
      authorizedCreateOnly={authorizedCreateOnly}
    />
  )
}

function ResearchPanelView({
  user,
  onClose,
  authorizedCreateOnly,
}: {
  user: AuthUser | null
  onClose: () => void
  authorizedCreateOnly: boolean
}) {
  const dialogRef = useRef<HTMLDivElement | null>(null)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [showAuthModal, setShowAuthModal] = useState(false)
  const [input, setInput] = useState('')
  const [localOnly, setLocalOnly] = useState(false)
  const [billingConsentState, setBillingConsentState] = useState({ key: '', checked: false })
  const taskPreferences = useQuery({
    queryKey: ['ai-task-preferences', user?.id ?? 'anonymous'],
    queryFn: () => listAITaskPreferences(),
    enabled: Boolean(user),
    retry: false,
  })
  const researchPreference = taskPreferences.data?.preferences.find(
    (preference) => preference.task_kind === 'deep_research',
  )
  const defaultPreference = taskPreferences.data?.preferences.find(
    (preference) => preference.task_kind === 'default',
  )
  const effectiveResearchPreference = researchPreference?.selection_state === 'available'
    ? researchPreference
    : researchPreference?.selection_state === 'inherit_default'
      && defaultPreference?.selection_state === 'available'
      && defaultPreference.model?.research_eligible === true
      ? defaultPreference
      : null
  const preferredSource = effectiveResearchPreference?.selection_source === 'byok'
    || effectiveResearchPreference?.selection_source === 'chatgpt_subscription'
    ? effectiveResearchPreference.selection_source : null
  const preferredModelConfigId = preferredSource === 'byok'
    ? effectiveResearchPreference?.model_config_id ?? null : null
  const preferredModel = effectiveResearchPreference?.model ?? null
  const preferredModelId = preferredSource === 'chatgpt_subscription'
    ? taskPreferences.data?.subscription.model_id ?? null
    : preferredModel?.model_id ?? null
  const hasPersonalSelection = Boolean(
    researchPreference?.selection_source === 'byok'
    || researchPreference?.selection_source === 'chatgpt_subscription'
    || (
      researchPreference?.selection_state === 'inherit_default'
      && defaultPreference?.selection_source === 'byok'
    )
  )
  const {
    sessions,
    activeSessionId,
    sessionResearchModel,
    canRestartEmptySession,
    messages,
    phase,
    searchResults,
    hasRecoverableTask,
    isBusy,
    recoveryAction,
    recoveryNotice,
    handleSend,
    handleNewSession,
    handleSelectSession,
    handleCancel,
    handleDisconnect,
    handleResume,
    handleRetry,
  } = useResearch(user?.id ?? null, { authorizedCreateOnly })

  const useSessionModel = Boolean(activeSessionId) && !canRestartEmptySession
  const researchSource = useSessionModel
    ? sessionResearchModel?.source ?? null : preferredSource
  const researchModelConfigId = researchSource === 'byok'
    ? useSessionModel
      ? sessionResearchModel?.model_config_id ?? null
      : preferredModelConfigId
    : null
  const researchModelId = useSessionModel
    ? sessionResearchModel?.model_id ?? null : preferredModelId
  const hasResearchModel = Boolean(
    researchSource && researchModelId
    && (researchSource === 'chatgpt_subscription' || researchModelConfigId)
  )
  const researchModelUnavailable = !useSessionModel && hasPersonalSelection && !hasResearchModel
  const researchModelLabel = useSessionModel
    ? researchModelId
    : preferredSource === 'chatgpt_subscription'
      ? `ChatGPT 订阅 · ${taskPreferences.data?.subscription.display_name ?? researchModelId ?? ''}`
      : preferredModel
        ? preferredModel.display_name === preferredModel.model_id
          ? preferredModel.display_name : `${preferredModel.display_name} (${preferredModel.model_id})`
        : null

  const billingConsentKey = JSON.stringify([
    user?.id ?? 'anonymous',
    researchSource ?? 'no-source',
    researchModelConfigId ?? researchModelId ?? 'no-model',
    activeSessionId ?? 'new-research',
  ])
  const billingConsent = billingConsentState.key === billingConsentKey && billingConsentState.checked

  const researchAuthorization: ResearchCreateAuthorization | undefined =
    hasResearchModel && billingConsent
      ? researchSource === 'byok' && researchModelConfigId
        ? { executionSource: 'byok', modelConfigId: researchModelConfigId, consent: true }
        : researchSource === 'chatgpt_subscription'
          ? { executionSource: 'chatgpt_subscription', consent: true }
          : undefined
      : undefined

  const isLoading = isBusy || phase === 'thinking' || phase === 'tool_calling' || phase === 'streaming'
  // Before receiving a Session-ID, a POST might already have reached Django.
  // First close surfaces the uncertainty; a second explicit close may dismiss.
  const [preHeaderWarningSeen, setPreHeaderWarningSeen] = useState(false)

  const handleClose = useCallback(() => {
    const needsRiskReview = !activeSessionId
      && (isLoading || recoveryAction === 'resume' || recoveryAction === 'retry')
      && !preHeaderWarningSeen
    handleDisconnect()
    setIsFullscreen(false)
    if (needsRiskReview) {
      setPreHeaderWarningSeen(true)
      return
    }
    setPreHeaderWarningSeen(false)
    onClose()
  }, [activeSessionId, handleDisconnect, isLoading, onClose, preHeaderWarningSeen, recoveryAction])

  function handleSendQuery() {
    if (!input.trim() || isLoading || hasRecoverableTask || !user || researchModelUnavailable) return
    // Do not admit an unauthenticated create while preferences are unknown; that
    // path hits personal_clients_for_user and becomes「研究服务暂时不可用」.
    if (taskPreferences.isLoading || taskPreferences.isPending) return
    if (authorizedCreateOnly && (recoveryAction === 'retry' || !hasResearchModel)) return
    if ((authorizedCreateOnly || hasPersonalSelection || hasResearchModel) && !researchAuthorization) return
    const submittedInput = input
    if (hasResearchModel && !billingConsent) return
    void handleSend(input.trim(), {
      localOnly,
      ...(researchAuthorization ? { authorization: researchAuthorization } : {}),
    }).then((accepted) => {
      if (accepted) {
        setInput((current) => current === submittedInput ? '' : current)
        setBillingConsentState({ key: '', checked: false })
      }
    })
  }

  function handleRetryQuery() {
    if (taskPreferences.isLoading || taskPreferences.isPending) return
    if (hasResearchModel && !billingConsent) return
    if ((authorizedCreateOnly || hasPersonalSelection || hasResearchModel) && !researchAuthorization) return
    void handleRetry(researchAuthorization).then((accepted) => {
      if (accepted) setBillingConsentState({ key: '', checked: false })
    })
  }

  function handleSuggestionClick(query: string) {
    if (!user) {
      setShowAuthModal(true)
      return
    }
    if (isBusy || hasRecoverableTask || researchModelUnavailable || (authorizedCreateOnly && recoveryAction === 'retry')) return
    if (authorizedCreateOnly && !hasResearchModel) return
    if (hasResearchModel && !billingConsent) {
      setInput(query)
      return
    }
    void handleSend(query, {
      localOnly: false,
      ...(researchAuthorization ? { authorization: researchAuthorization } : {}),
    }).then((accepted) => {
      if (accepted) setBillingConsentState({ key: '', checked: false })
    })
  }

  function handleStartNewSession() {
    setBillingConsentState({ key: '', checked: false })
    handleNewSession()
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
          className="fixed inset-0 z-30 bg-black/25 backdrop-blur-sm transition-opacity pointer-events-auto dark:bg-black/55"
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
        className={`research-panel fixed z-40 flex flex-col overflow-hidden rounded-t-2xl border border-border bg-card text-card-foreground
          shadow-[0_24px_80px_-24px_rgba(0,0,0,0.45)] sm:rounded-2xl
          transition-all duration-300 ease-out pointer-events-auto
          ${isFullscreen
            ? 'inset-2 rounded-2xl'
            : 'bottom-[60px] right-0 h-[min(760px,calc(100dvh-7rem))] w-[min(620px,calc(100vw-3rem))] sm:right-6 max-[640px]:inset-x-0 max-[640px]:bottom-0 max-[640px]:h-[88dvh] max-[640px]:w-auto'
          }`}
      >
        <ResearchHeader
          title={panelTitle}
          phase={phase}
          isFullscreen={isFullscreen}
          onToggleFullscreen={() => setIsFullscreen((fullscreen) => !fullscreen)}
          onNewSession={handleStartNewSession}
          onClose={handleClose}
          sessions={sessions}
          activeSessionId={activeSessionId}
          onSelectSession={handleSelectSession}
        />

        <div className="flex-1 space-y-3 overflow-y-auto overscroll-contain bg-gradient-to-b from-secondary/65 via-background/90 to-background px-4 py-3">
          {!user ? (
            <div className="flex flex-col items-center justify-center h-full text-center px-6">
              <div className="mb-4 flex size-14 items-center justify-center rounded-2xl bg-primary/10 shadow-lg shadow-primary/10">
                <LogIn className="size-7 text-primary" />
              </div>
              <p className="text-base font-bold text-foreground">需要登录</p>
              <p className="mt-1.5 max-w-[260px] text-xs leading-relaxed text-muted-foreground">
                研究助手需要登录后才能使用，登录即可开始深度新闻分析
              </p>
              <Button type="button" className="mt-5 rounded-full" onClick={() => setShowAuthModal(true)}>
                登录 / 注册
              </Button>
            </div>
          ) : (
            <>
              {canRestartEmptySession && (
                <div role="status" className="rounded-xl border border-border bg-muted/50 p-3 text-xs text-muted-foreground">
                  此会话尚未生成回答。确认当前模型后，发送问题将新建研究，原记录会保留。
                </div>
              )}
              {authorizedCreateOnly && useSessionModel && (
                <div role="status" className="rounded-xl border border-border bg-muted/50 p-3 text-xs text-muted-foreground">
                  续问使用会话原模型来源，不能切换账号或供应商。每次发送前请重新确认对应额度或费用；旧会话缺少安全续接记录时，请新建研究。
                </div>
              )}
              {researchModelUnavailable && (
                <div role="status" className="rounded-xl border border-border bg-muted/50 p-3 text-xs text-muted-foreground">
                  所选模型尚未完成研究所需的文本与工具能力验证，或连接已失效。请到 AI 设置检查；不会自动改用其他模型。
                </div>
              )}
              {authorizedCreateOnly && !useSessionModel && !hasResearchModel && (
                <div role="status" className="rounded-xl border border-border bg-muted/50 p-3 text-xs text-muted-foreground">
                  请先到 AI 设置中配置并验证支持工具调用的个人模型或 ChatGPT 订阅模型，再返回开始研究。
                </div>
              )}
              {hasResearchModel && researchModelLabel && !hasRecoverableTask && (
                <section
                  aria-labelledby="research-model-consent-title"
                  className="rounded-xl border border-primary/20 bg-primary/5 p-3 text-xs leading-relaxed"
                  data-testid="research-model-consent"
                >
                  <p id="research-model-consent-title" className="font-semibold text-foreground">
                    本次研究模型：{researchModelLabel}
                    {!activeSessionId && researchPreference?.selection_state === 'inherit_default' ? '（已保存的个人默认模型）' : ''}
                  </p>
                  <p className="mt-1 text-muted-foreground">
                    {researchSource === 'chatgpt_subscription'
                      ? '发送的问题和相关内容由当前 ChatGPT 订阅模型处理，可能使用订阅额度。'
                      : '发送的问题和相关内容由已保存模型的服务商处理，可能产生服务商费用。'}
                  </p>
                  <label className="mt-2 flex cursor-pointer items-start gap-2 text-foreground">
                    <Checkbox
                      checked={billingConsent}
                      onChange={(event) => setBillingConsentState({
                        key: billingConsentKey,
                        checked: event.currentTarget.checked,
                      })}
                      aria-label="同意本次研究调用"
                      className="mt-0.5"
                    />
                    <span>{researchSource === 'chatgpt_subscription'
                      ? '同意本次发送内容并使用 ChatGPT 订阅额度。'
                      : '同意本次发送内容及服务商可能产生的费用。'}</span>
                  </label>
                </section>
              )}
              <ResearchMessageList
                messages={recoveryAction === 'resume' || recoveryAction === 'retry'
                  ? messages.filter(message => !message.id.endsWith(':notice')) : messages}
                phase={phase}
                searchResults={searchResults}
                onSuggestionClick={handleSuggestionClick}
                disabled={isBusy}
              />
              {recoveryAction === 'resume' && !(authorizedCreateOnly && !activeSessionId) && (
                <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-500/25 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-200">
                  <span>{authorizedCreateOnly ? '只会读取此会话已有任务事件；若任务仍在排队，不会重新派发模型任务。' : !activeSessionId ? '原请求可能已到达服务器。继续接收将复用原请求标识，避免创建新的重复任务；暂时无法确认后台是否已经开始。' : '浏览器连接已停止；后台任务可能仍在执行。重新连接会回放当前任务的事件。'}</span>
                  <Button type="button" size="sm" variant="outline" onClick={() => void handleResume()}>
                    继续接收
                  </Button>
                </div>
              )}
              {authorizedCreateOnly && recoveryAction === 'resume' && !activeSessionId && (
                <div role="status" className="rounded-xl border border-amber-500/25 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-200">
                  原请求尚未确认对应会话。为避免重新派发或重复计费，此模式不会重放新建请求；可先从历史会话中查看已保存结果。
                </div>
              )}
              {authorizedCreateOnly && recoveryAction === 'retry' && (
                <div role="status" className="rounded-xl border border-rose-500/25 bg-rose-500/10 p-3 text-xs text-rose-700 dark:text-rose-200">
                  上次结果尚未确认。此模式不自动重试；请先查看历史会话，或在新研究中重新选择模型并确认额度或费用。
                </div>
              )}
              {recoveryAction === 'retry' && !authorizedCreateOnly && (
                <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-rose-500/25 bg-rose-500/10 p-3 text-xs text-rose-700 dark:text-rose-200">
                  <span>{activeSessionId && recoveryNotice
                    ? `${recoveryNotice} 重新研究会创建新任务，可能重复计算或产生费用。`
                    : '原请求可能已到达服务器。只有点击下方按钮才会新建任务，可能重复计算或产生费用。'}</span>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={handleRetryQuery}
                    disabled={hasResearchModel && !billingConsent}
                  >
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
          loginRequired={!user}
          disabled={!user || hasRecoverableTask || researchModelUnavailable
            || (authorizedCreateOnly && (recoveryAction === 'retry' || !hasResearchModel))
            || (hasResearchModel && !billingConsent)}
          localOnly={localOnly}
          onToggleLocalOnly={() => setLocalOnly((enabled) => !enabled)}
        />
      </div>

      {showAuthModal && <AuthModal onClose={() => setShowAuthModal(false)} />}
    </>
  )
}
