import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ConnectionRequestError, hasAIConnectionAuthentication, listAIConnections, listAIModels,
  type AIConnection, type AIModel,
} from '@/services/aiConnectionsApi'

interface Choice { connection: AIConnection; model: AIModel }

/** GET-only personal model list. Selecting does not grant billing consent. */
interface PickerProps {
  viewer: number
  selected: string | null
  consent: boolean
  onSelect: (modelId: string | null) => void
  onConsent: (confirmed: boolean) => void
  disabled: boolean
}

/** A new viewer always gets an entirely new component state and GET cache. */
export default function ChatModelPicker(props: PickerProps) {
  return <ChatModelSession key={props.viewer} {...props} />
}

function ChatModelSession({
  viewer, selected, consent, onSelect, onConsent, disabled,
}: {
  viewer: number
  selected: string | null
  consent: boolean
  onSelect: (modelId: string | null) => void
  onConsent: (confirmed: boolean) => void
  disabled: boolean
}) {
  const [choices, setChoices] = useState<Choice[] | null>(null)
  const [error, setError] = useState(false)
  const [disabledBySite, setDisabledBySite] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    void (async () => {
      try {
        const connections = (await listAIConnections(controller.signal)).filter(
          connection => connection.is_enabled && hasAIConnectionAuthentication(connection),
        )
        const models = await Promise.all(connections.map(connection => listAIModels(connection, controller.signal)))
        if (controller.signal.aborted) return
        setChoices(connections.flatMap((connection, index) => models[index]
          .filter(model => model.has_trusted_route && model.capabilities.text === 'supported' && model.article_chat_supported === true)
          .map(model => ({ connection, model }))))
      } catch (reason) {
        if (!controller.signal.aborted) {
          setChoices(null)
          // A read-only site or disabled BYOK feature is normal; do not show
          // an account-error banner on every user's existing chat dialog.
          setDisabledBySite(reason instanceof ConnectionRequestError && reason.status === 403)
          setError(!(reason instanceof ConnectionRequestError && reason.status === 403))
        }
      }
    })()
    return () => controller.abort()
  }, [viewer])

  if (disabledBySite) return null
  return <section aria-label="个人聊天模型" className="border-b border-border bg-card px-4 py-2 text-xs md:px-6">
    <div className="flex min-w-0 flex-wrap items-center gap-2">
      <label className="flex min-w-0 flex-1 items-center gap-2">
        <span className="shrink-0 font-medium">本轮回答</span>
        <select
          aria-label="本轮聊天模型"
          className="h-9 min-w-0 flex-1 rounded-md border border-input bg-background px-2"
          value={selected ?? ''}
          disabled={disabled || choices === null}
          onChange={event => onSelect(event.target.value || null)}
        >
          <option value="">原有聊天方式（不使用个人 BYOK）</option>
          {selected && !choices?.some(choice => choice.model.id === selected) &&
            <option value={selected} disabled>原模型已失效，请重新选择</option>}
          {choices?.map(({ connection, model }) => (
            <option key={model.id} value={model.id}>{connection.display_name} · {model.display_name}</option>
          ))}
        </select>
      </label>
      <Link to="/settings/ai" className="shrink-0 text-primary underline">模型设置</Link>
    </div>
    {error && <p role="alert" className="mt-1">暂时无法读取个人模型，仍可使用原有聊天方式；请重新打开助手重试。</p>}
    {choices?.length === 0 && <p className="mt-1 text-muted-foreground">当前没有可用于文章聊天的个人模型。请在模型设置中验证文本能力并确认问答用途可用。</p>}
    {selected && <label className="mt-2 flex items-start gap-2">
      <input type="checkbox" checked={consent} disabled={disabled || !choices?.some(choice => choice.model.id === selected)}
        onChange={event => onConsent(event.target.checked)} />
      <span>我确认这次个人模型问答可能产生服务商费用。模型选择仅适用于之后发送的问题，不会自动重发或改写历史。</span>
    </label>}
    {selected && <p className="mt-1 text-muted-foreground">个人模型暂不支持联网搜索；
      {choices?.find(choice => choice.model.id === selected)?.model.delivery_mode === 'buffered'
        ? '本轮完整生成后显示（buffered）。' : '仅在服务端验证完成后保存回答。'}不会自动切换模型。</p>}
  </section>
}
