import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import axios from 'axios'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '@/context/AuthContext'
import {
  activateChatGPTSubscriptionConnection,
  cancelChatGPTSubscriptionAttempt,
  fetchChatGPTSubscriptionAttempt,
  disconnectChatGPTSubscription,
  fetchChatGPTSubscriptionModels,
  fetchChatGPTSubscriptionStatus,
  selectChatGPTSubscriptionModel,
  startChatGPTSubscriptionConnect,
} from '@/services/api'
import type { ChatGPTSubscriptionAttemptStatus, ChatGPTSubscriptionConnection } from '@/services/api'
import { newsKeys } from '@/services/newsQueries'

const subscriptionRootKey = ['chatgptSubscription'] as const
const ATTEMPT_POLL_INTERVAL_MS = 2_000
const POPUP_CLOSE_CHECK_INTERVAL_MS = 500
const TERMINAL_ATTEMPT_STATUSES: ReadonlySet<ChatGPTSubscriptionAttemptStatus['status']> = new Set([
  'completed', 'failed', 'cancelled',
])
type ConnectRequestIdentity = { generation: number; ownerId: number }

function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const body: unknown = error.response?.data
    if (typeof body === 'object' && body !== null && !Array.isArray(body) && 'error' in body) {
      const message = (body as { error?: unknown }).error
      if (typeof message === 'string') return message
    }
  }
  return error instanceof Error ? error.message : '请求失败，请稍后重试。'
}

function connectionLabel(connection: ChatGPTSubscriptionConnection): string {
  return connection.account_name || connection.account_email || `订阅账号 ${connection.id.slice(0, 8)}`
}

export default function ChatGPTSubscriptionSettings() {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const [connectPending, setConnectPending] = useState(false)
  const [attemptId, setAttemptId] = useState<string | null>(null)
  const [notice, setNotice] = useState('')
  const popupRef = useRef<Window | null>(null)
  const attemptIdRef = useRef<string | null>(null)
  const attemptOwnerRef = useRef<number | null>(null)
  const finishedAttemptRef = useRef<string | null>(null)
  const connectRequestGenerationRef = useRef(0)
  const activeConnectRequestRef = useRef<ConnectRequestIdentity | null>(null)
  const observedUserIdRef = useRef<number | undefined>(user?.id)

  useLayoutEffect(() => () => {
    connectRequestGenerationRef.current += 1
    activeConnectRequestRef.current = null
    popupRef.current?.close()
    popupRef.current = null
  }, [])

  const statusQuery = useQuery({
    queryKey: [...subscriptionRootKey, 'status', user?.id ?? 'anonymous'],
    queryFn: fetchChatGPTSubscriptionStatus,
    enabled: Boolean(user),
    retry: false,
  })
  const activeConnection = useMemo(() => {
    const id = statusQuery.data?.active_connection_id
    return statusQuery.data?.connections.find((connection) => connection.id === id) ?? null
  }, [statusQuery.data])
  const modelsQuery = useQuery({
    queryKey: [...subscriptionRootKey, 'models', user?.id ?? 'anonymous', activeConnection?.id],
    queryFn: () => fetchChatGPTSubscriptionModels(activeConnection!.id),
    enabled: Boolean(activeConnection?.connected),
    staleTime: 0,
  })
  const attemptQuery = useQuery({
    queryKey: [...subscriptionRootKey, 'attempt', user?.id ?? 'anonymous', attemptId],
    queryFn: ({ signal }) => fetchChatGPTSubscriptionAttempt(attemptId!, signal),
    enabled: Boolean(user && attemptId),
    refetchInterval: (query) => {
      if (!attemptId || query.state.status === 'error' ||
        (query.state.data && TERMINAL_ATTEMPT_STATUSES.has(query.state.data.status))) {
        return false
      }
      // The server makes expired attempts terminal during status reads. Pause
      // on transport errors so the user can explicitly resume one check.
      return ATTEMPT_POLL_INTERVAL_MS
    },
    retry: false,
  })

  const invalidatePrivateNews = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: subscriptionRootKey }),
      queryClient.invalidateQueries({ queryKey: newsKeys.details() }),
    ])
  }, [queryClient])

  const activateMutation = useMutation({
    mutationFn: activateChatGPTSubscriptionConnection,
    onSuccess: invalidatePrivateNews,
  })
  const selectModelMutation = useMutation({
    mutationFn: ({ id, slug }: { id: string; slug: string }) => selectChatGPTSubscriptionModel(id, slug),
    onSuccess: invalidatePrivateNews,
  })
  const disconnectMutation = useMutation({
    mutationFn: disconnectChatGPTSubscription,
    onSuccess: async (result) => {
      await invalidatePrivateNews()
      setNotice(result.revocation_confirmed
        ? '订阅账号已断开，OpenAI 已确认撤销令牌。'
        : '本地凭据已清除；OpenAI 未确认撤销令牌。')
    },
  })

  const finishConnect = useCallback(async (currentAttemptId: string, message: string, completed = false) => {
    if (attemptIdRef.current !== currentAttemptId || finishedAttemptRef.current === currentAttemptId) return
    finishedAttemptRef.current = currentAttemptId
    if (completed) await invalidatePrivateNews()
    if (attemptIdRef.current !== currentAttemptId) return
    setConnectPending(false)
    setNotice(message)
    popupRef.current?.close()
    popupRef.current = null
    activeConnectRequestRef.current = null
    attemptOwnerRef.current = null
    attemptIdRef.current = null
    setAttemptId(null)
  }, [invalidatePrivateNews])

  const cancelAttemptMutation = useMutation({
    mutationFn: cancelChatGPTSubscriptionAttempt,
    onSuccess: async (attempt) => {
      if (attempt.status === 'completed') {
        await finishConnect(attempt.id, 'ChatGPT 订阅账号已连接。', true)
      } else if (TERMINAL_ATTEMPT_STATUSES.has(attempt.status)) {
        await finishConnect(attempt.id, attempt.message || 'ChatGPT 订阅连接未完成。')
      } else {
        queryClient.setQueryData(
          [...subscriptionRootKey, 'attempt', user?.id ?? 'anonymous', attempt.id],
          attempt,
        )
        setNotice('服务器仍在处理此授权请求，状态检查会继续。')
      }
    },
  })

  useEffect(() => {
    const attempt = attemptQuery.data
    if (!attemptId || !attempt || attempt.id !== attemptId) return
    if (attempt.status === 'completed') {
      void finishConnect(attempt.id, 'ChatGPT 订阅账号已连接。', true)
    } else if (TERMINAL_ATTEMPT_STATUSES.has(attempt.status)) {
      void finishConnect(attempt.id, attempt.message || 'ChatGPT 订阅连接未完成。')
    }
  }, [attemptId, attemptQuery.data, finishConnect])

  useLayoutEffect(() => {
    if (observedUserIdRef.current === user?.id) return
    observedUserIdRef.current = user?.id
    connectRequestGenerationRef.current += 1
    if (attemptOwnerRef.current === null || user?.id === attemptOwnerRef.current) return
    activeConnectRequestRef.current = null
    const stalePopup = popupRef.current
    popupRef.current = null
    stalePopup?.close()
    setConnectPending(false)
    attemptIdRef.current = null
    setAttemptId(null)
    attemptOwnerRef.current = null
    finishedAttemptRef.current = null
    setNotice('本地登录账号已切换，此授权请求已停止。')
  }, [user?.id])

  useEffect(() => {
    if (!connectPending) return
    const timer = window.setInterval(() => {
      const popup = popupRef.current
      if (popup && popup.closed) {
        window.clearInterval(timer)
        popupRef.current = null
        setNotice('授权窗口已关闭或无法由本页访问；仍以服务器状态为准，检查会继续。')
      }
    }, POPUP_CLOSE_CHECK_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [connectPending])

  async function beginConnect(connectionId?: string) {
    const ownerId = user?.id
    if (ownerId === undefined) return
    const requestGeneration = ++connectRequestGenerationRef.current
    const requestIdentity = { generation: requestGeneration, ownerId }
    activeConnectRequestRef.current = requestIdentity
    setNotice('')
    attemptIdRef.current = null
    setAttemptId(null)
    attemptOwnerRef.current = ownerId
    finishedAttemptRef.current = null
    const previousPopup = popupRef.current
    popupRef.current = null
    previousPopup?.close()
    const popup = window.open('about:blank', '_blank', 'popup,width=560,height=760')
    const isCurrentRequest = () => (
      activeConnectRequestRef.current === requestIdentity &&
      connectRequestGenerationRef.current === requestGeneration &&
      observedUserIdRef.current === ownerId &&
      attemptOwnerRef.current === ownerId
    )
    if (!popup) {
      if (!isCurrentRequest()) return
      activeConnectRequestRef.current = null
      attemptOwnerRef.current = null
      setNotice('浏览器拦截了授权窗口，请允许此站点打开弹窗后重试。')
      return
    }
    popupRef.current = popup
    setConnectPending(true)
    try {
      const handoff = await startChatGPTSubscriptionConnect(connectionId)
      if (!isCurrentRequest()) return
      attemptIdRef.current = handoff.attempt_id
      setAttemptId(handoff.attempt_id)
      if (popup.closed || popupRef.current !== popup) {
        if (popupRef.current === popup) popupRef.current = null
        setNotice('授权窗口已关闭或无法由本页访问；正在等待服务器终态或过期。')
        return
      }
      const form = popup.document.createElement('form')
      form.method = 'POST'
      form.action = handoff.handoff_url
      for (const [name, value] of [
        ['attempt_id', handoff.attempt_id],
        ['handoff_token', handoff.handoff_token],
      ]) {
        const input = popup.document.createElement('input')
        input.type = 'hidden'
        input.name = name
        input.value = value
        form.append(input)
      }
      popup.document.body.replaceChildren(form)
      form.submit()
    } catch (error) {
      if (!isCurrentRequest()) return
      if (popupRef.current === popup) {
        popup.close()
        popupRef.current = null
      }
      if (attemptIdRef.current) {
        setNotice(`授权窗口启动未完成，服务器状态仍会检查：${errorMessage(error)}`)
      } else {
        activeConnectRequestRef.current = null
        attemptOwnerRef.current = null
        setConnectPending(false)
        setNotice(errorMessage(error))
      }
    }
  }

  if (!user) {
    return (
      <section className="mx-auto max-w-3xl px-4 py-10">
        <h1 className="text-2xl font-semibold">ChatGPT 订阅连接</h1>
        <p className="mt-3 text-muted-foreground">请先登录 NewsHub 本地账号，再管理此账号自己的 ChatGPT 订阅连接。</p>
      </section>
    )
  }

  return (
    <section className="mx-auto max-w-3xl px-4 py-10">
      <header className="mb-6">
        <p className="text-sm font-medium text-orange-600">本地订阅连接</p>
        <h1 className="mt-1 text-2xl font-semibold">ChatGPT 订阅设置</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          连接只属于当前 NewsHub 用户。全文翻译使用此处选中的 ChatGPT 账号和可见模型。
        </p>
      </header>

      <div className="mb-5 rounded-xl border border-border bg-card p-4 text-sm text-muted-foreground">
        OAuth 在单独窗口中通过 OpenAI 官方授权完成。令牌只保存在本地后端，不会写入浏览器存储。
      </div>

      {notice && <p role="status" className="mb-4 rounded-lg bg-muted px-3 py-2 text-sm">{notice}</p>}
      {statusQuery.isError && <p role="alert" className="mb-4 text-sm text-destructive">{errorMessage(statusQuery.error)}</p>}
      {attemptId && attemptQuery.error && (
        <div className="mb-4 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm">
          <p role="alert" className="text-destructive">
            状态检查暂时失败，授权请求仍保留在服务器；自动检查已暂停。{` ${errorMessage(attemptQuery.error)}`}
          </p>
          <button
            type="button"
            onClick={() => void attemptQuery.refetch()}
            disabled={attemptQuery.isFetching}
            className="mt-2 rounded-md border border-border px-3 py-1.5 disabled:opacity-50"
          >{attemptQuery.isFetching ? '正在重试…' : '重试状态检查'}</button>
        </div>
      )}
      {cancelAttemptMutation.isError && (
        <p role="alert" className="mb-4 text-sm text-destructive">
          {`取消授权失败：${errorMessage(cancelAttemptMutation.error)}`}
        </p>
      )}
      {activateMutation.isError && <p role="alert" className="mb-4 text-sm text-destructive">{errorMessage(activateMutation.error)}</p>}
      {selectModelMutation.isError && <p role="alert" className="mb-4 text-sm text-destructive">{errorMessage(selectModelMutation.error)}</p>}
      {disconnectMutation.isError && <p role="alert" className="mb-4 text-sm text-destructive">{errorMessage(disconnectMutation.error)}</p>}

      <div className="mb-5 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => void beginConnect()}
          disabled={connectPending}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
        >
          {connectPending ? '等待 OpenAI 授权…' : '连接新账号'}
        </button>
        <button
          type="button"
          onClick={() => void statusQuery.refetch()}
          disabled={statusQuery.isFetching}
          className="rounded-lg border border-border px-4 py-2 text-sm disabled:opacity-50"
        >
          刷新状态
        </button>
        {connectPending && attemptId && (
          <button
            type="button"
            onClick={() => cancelAttemptMutation.mutate(attemptId)}
            disabled={cancelAttemptMutation.isPending}
            className="rounded-lg border border-destructive/40 px-4 py-2 text-sm text-destructive disabled:opacity-50"
          >{cancelAttemptMutation.isPending ? '正在取消…' : '取消授权'}</button>
        )}
      </div>

      {statusQuery.isLoading ? (
        <p className="text-sm text-muted-foreground">正在读取订阅连接…</p>
      ) : statusQuery.data?.connections.length ? (
        <div className="space-y-3">
          {statusQuery.data.connections.map((connection) => (
            <article key={connection.id} className="rounded-xl border border-border bg-card p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="font-medium">{connectionLabel(connection)}</h2>
                  {connection.account_email && <p className="mt-1 text-sm text-muted-foreground">{connection.account_email}</p>}
                  <p className="mt-1 text-xs text-muted-foreground">
                    {connection.needs_reauth ? '需要重新授权' : connection.connected ? '已连接' : '已断开'}
                    {connection.active ? ' · 当前使用' : ''}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {!connection.active && connection.connected && (
                    <button
                      type="button"
                      onClick={() => activateMutation.mutate(connection.id)}
                      disabled={activateMutation.isPending}
                      className="rounded-md border border-border px-3 py-1.5 text-sm disabled:opacity-50"
                    >设置为当前账号</button>
                  )}
                  <button
                    type="button"
                    onClick={() => void beginConnect(connection.id)}
                    disabled={connectPending}
                    className="rounded-md border border-border px-3 py-1.5 text-sm disabled:opacity-50"
                  >重新连接</button>
                  {connection.connected && (
                    <button
                      type="button"
                      onClick={() => disconnectMutation.mutate(connection.id)}
                      disabled={disconnectMutation.isPending}
                      className="rounded-md border border-destructive/40 px-3 py-1.5 text-sm text-destructive disabled:opacity-50"
                    >断开</button>
                  )}
                </div>
              </div>

              {connection.active && connection.connected && (
                <div className="mt-4 border-t border-border pt-4">
                  <div className="flex flex-wrap items-end gap-3">
                    <label className="min-w-64 flex-1 text-sm">
                      <span className="mb-1 block font-medium">可见模型</span>
                      <select
                        value={modelsQuery.data?.selected_model || connection.selected_model}
                        onChange={(event) => selectModelMutation.mutate({ id: connection.id, slug: event.target.value })}
                        disabled={modelsQuery.isLoading || modelsQuery.isError || selectModelMutation.isPending || !(modelsQuery.data?.models.length)}
                        className="w-full rounded-lg border border-border bg-background px-3 py-2 disabled:opacity-60"
                      >
                        <option value="">{modelsQuery.isLoading ? '读取模型列表…' : '选择模型'}</option>
                        {modelsQuery.data?.models.map((model) => (
                          <option key={model.slug} value={model.slug}>{model.display_name}</option>
                        ))}
                      </select>
                    </label>
                    <button
                      type="button"
                      onClick={() => void modelsQuery.refetch()}
                      disabled={modelsQuery.isFetching}
                      className="rounded-lg border border-border px-3 py-2 text-sm disabled:opacity-50"
                    >刷新模型</button>
                  </div>
                  {modelsQuery.isError && <p role="alert" className="mt-2 text-sm text-destructive">{errorMessage(modelsQuery.error)}</p>}
                  {!connection.selected_model && !modelsQuery.isLoading && modelsQuery.data?.models.length === 0 && (
                    <p className="mt-2 text-sm text-muted-foreground">此账号目前没有可见模型。</p>
                  )}
                  {!connection.selected_model && modelsQuery.data?.models.length ? (
                    <p className="mt-2 text-sm text-muted-foreground">选择模型后即可使用订阅全文翻译。</p>
                  ) : null}
                </div>
              )}
            </article>
          ))}
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
          尚未连接 ChatGPT 订阅账号。
        </div>
      )}
    </section>
  )
}
