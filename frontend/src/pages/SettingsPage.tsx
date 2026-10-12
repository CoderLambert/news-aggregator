import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import axios from 'axios'
import type { LucideIcon } from 'lucide-react'
import { AlignLeft, ArrowLeft, Bot, Check, GitCompareArrows, KeyRound, Languages, LockKeyhole, Trash2, Type } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useAuth } from '@/context/AuthContext'
import { useLanguage } from '@/context/useLanguage'
import type { DisplayMode } from '@/types/news'
import { useCapabilities } from '@/context/CapabilitiesContext'
import {
  deleteProviderCredential,
  fetchProviderCredentialStatus,
  saveProviderCredential,
} from '@/services/api'
import type { PersonalProvider, ProviderCredentialStatus } from '@/services/api'

const DISPLAY_MODES = [
  { key: 'zh', label: '中文', description: '优先显示中文内容', icon: Type },
  { key: 'original', label: '原文', description: '优先显示来源原文', icon: Languages },
  { key: 'bilingual', label: '双文', description: '中文与原文一起阅读', icon: AlignLeft },
] satisfies ReadonlyArray<{ key: DisplayMode; label: string; description: string; icon: LucideIcon }>

const MODEL_PROVIDERS: ReadonlyArray<{
  id: PersonalProvider
  label: string
  defaultModel: string
}> = [
  { id: 'openai', label: 'OpenAI', defaultModel: 'gpt-5-mini' },
  { id: 'anthropic', label: 'Anthropic Claude', defaultModel: 'claude-sonnet-4-6' },
  { id: 'deepseek', label: 'DeepSeek', defaultModel: 'deepseek-chat' },
  { id: 'gemini', label: 'Google Gemini', defaultModel: 'gemini-2.5-flash' },
  { id: 'qwen', label: 'Qwen', defaultModel: 'qwen-plus' },
  { id: 'glm', label: 'GLM / Z.AI', defaultModel: 'glm-4.7' },
  { id: 'kimi', label: 'Kimi / Moonshot', defaultModel: 'kimi-k2.5' },
  { id: 'mistral', label: 'Mistral AI', defaultModel: 'mistral-small-latest' },
  { id: 'groq', label: 'Groq', defaultModel: 'llama-3.3-70b-versatile' },
  { id: 'xai', label: 'xAI', defaultModel: 'grok-4.3' },
  { id: 'openrouter', label: 'OpenRouter', defaultModel: 'openai/gpt-4o-mini' },
]

function requestError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const body: unknown = error.response?.data
    if (typeof body === 'object' && body !== null && !Array.isArray(body) && 'error' in body) {
      const message = (body as { error?: unknown }).error
      if (typeof message === 'string') return message
    }
  }
  return error instanceof Error ? error.message : '请求失败，请稍后重试。'
}

function PersonalApiKeySettings({ userId }: { userId: number }) {
  const [provider, setProvider] = useState<PersonalProvider>('deepseek')
  const [modelId, setModelId] = useState('deepseek-chat')
  const [apiKey, setApiKey] = useState('')
  const [credential, setCredential] = useState<ProviderCredentialStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    void fetchProviderCredentialStatus(controller.signal).then((value) => {
      setCredential(value)
      if (value.provider) setProvider(value.provider)
      if (value.modelId) setModelId(value.modelId)
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(requestError(reason))
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false)
    })
    return () => controller.abort()
  }, [userId])

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSaving(true)
    setError('')
    setNotice('')
    try {
      const value = await saveProviderCredential(provider, modelId, apiKey)
      setCredential(value)
      setApiKey('')
      setNotice('API Key 与模型已加密保存。后续个人 AI 请求将通过 LiteLLM 安全路由。')
    } catch (reason) {
      setError(requestError(reason))
    } finally {
      setSaving(false)
    }
  }

  const remove = async () => {
    if (!window.confirm('确定删除当前用户保存的 API Key？')) return
    setSaving(true)
    setError('')
    setNotice('')
    try {
      setCredential(await deleteProviderCredential())
      setApiKey('')
      setNotice('已删除保存的 API Key。')
    } catch (reason) {
      setError(requestError(reason))
    } finally {
      setSaving(false)
    }
  }

  return (
    <section aria-labelledby="api-key-settings" className="rounded-2xl border border-border bg-card p-5 sm:p-6">
      <div className="flex gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-orange-50 text-orange-600"><KeyRound aria-hidden="true" className="size-5" /></span>
        <div>
          <h2 id="api-key-settings" className="text-lg font-semibold">个人模型 API Key</h2>
          <p className="mt-1 text-sm leading-6 text-muted-foreground">Key 仅供当前账号的翻译、文章问答、推荐问题和深度研究使用；服务端加密保存，经本站 LiteLLM 路由发送到你选择的厂商，保存后不再回显。</p>
        </div>
      </div>

      <form className="mt-5 space-y-4" onSubmit={save}>
        <div className="grid gap-4 sm:grid-cols-3">
          <label className="space-y-2 text-sm font-medium">
            <span>模型提供方</span>
            <select
              value={provider}
              onChange={(event) => {
                const next = event.target.value as PersonalProvider
                setProvider(next)
                setModelId(MODEL_PROVIDERS.find((item) => item.id === next)?.defaultModel ?? '')
              }}
              disabled={saving || loading}
              className="flex h-11 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
            >
              {MODEL_PROVIDERS.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
            </select>
          </label>
          <label className="space-y-2 text-sm font-medium">
            <span>Model ID</span>
            <Input
              value={modelId}
              onChange={(event) => setModelId(event.target.value)}
              placeholder={MODEL_PROVIDERS.find((item) => item.id === provider)?.defaultModel}
              autoComplete="off"
              spellCheck={false}
              disabled={saving || loading}
              required
              maxLength={128}
              className="h-11"
            />
          </label>
          <label className="space-y-2 text-sm font-medium">
            <span>{credential?.configured ? '输入新 Key 以替换' : 'API Key'}</span>
            <Input
              type="password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder="请输入厂商 API Key"
              autoComplete="new-password"
              spellCheck={false}
              disabled={saving || loading}
              required
              minLength={8}
              maxLength={512}
              className="h-11"
            />
          </label>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" className="h-11" disabled={saving || loading || apiKey.trim().length < 8}>
            {saving ? '正在保存…' : credential?.configured ? '替换 Key' : '保存 Key'}
          </Button>
          {(credential?.configured || credential?.requiresReplacement) && <Button type="button" variant="outline" className="h-11 text-red-700" disabled={saving} onClick={() => void remove()}>
            <Trash2 aria-hidden="true" />删除 Key
          </Button>}
          <span className="text-sm text-muted-foreground">
            {loading ? '正在读取状态…' : credential?.configured
              ? `已配置：${credential.providerLabel ?? credential.provider} / ${credential.modelId}`
              : credential?.requiresReplacement ? '旧版直连凭据已停用，请替换' : '尚未配置'}
          </span>
        </div>
        {notice && <p role="status" className="text-sm text-emerald-700">{notice}</p>}
        {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      </form>
    </section>
  )
}

export default function SettingsPage() {
  const { lang, setLang, displayMode, setDisplayMode, t } = useLanguage()
  const { user } = useAuth()
  const { capabilities } = useCapabilities()
  const canManageChatGPT = capabilities.features.accounts.enabled && capabilities.features.chatgpt_subscription.enabled
  const canCompareProviders = capabilities.features.provider_comparisons.enabled && Boolean(user?.isSuperuser)
  const canManageAdmin = capabilities.features.admin.enabled && Boolean(user?.isSuperuser)

  return (
    <section className="mx-auto w-full max-w-3xl px-4 pb-12 pt-6 sm:pt-10">
      <Link to="/" className="inline-flex min-h-11 items-center gap-2 rounded-md text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <ArrowLeft aria-hidden="true" className="size-4" />返回首页
      </Link>

      <header className="mb-8 mt-4">
        <p className="text-sm font-medium text-orange-600">个人设置</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight">设置</h1>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">调整阅读方式，管理账号连接和站点工具。</p>
      </header>

      <div className="space-y-6">
        <section aria-labelledby="reading-settings" className="rounded-2xl border border-border bg-card p-5 sm:p-6">
          <div className="mb-5">
            <h2 id="reading-settings" className="text-lg font-semibold">阅读偏好</h2>
            <p className="mt-1 text-sm text-muted-foreground">显示模式会应用到新闻列表和详情页。</p>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            {DISPLAY_MODES.map((mode) => {
              const Icon = mode.icon
              const selected = displayMode === mode.key
              return (
                <button
                  key={mode.key}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => setDisplayMode(mode.key)}
                  className={`relative min-h-24 rounded-xl border p-4 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${selected ? 'border-orange-400 bg-orange-50 text-orange-950' : 'border-border hover:bg-muted/60'}`}
                >
                  <span className="flex items-center gap-2 font-medium"><Icon aria-hidden="true" className="size-4" />{mode.label}</span>
                  <span className="mt-2 block text-xs leading-5 text-muted-foreground">{mode.description}</span>
                  {selected && <Check aria-hidden="true" className="absolute right-3 top-3 size-4 text-orange-600" />}
                </button>
              )
            })}
          </div>
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-5">
            <div>
              <p className="text-sm font-medium">界面语言</p>
              <p className="mt-1 text-xs text-muted-foreground">调整导航和操作文字。</p>
            </div>
            <div className="flex rounded-lg border border-border p-1" role="group" aria-label="界面语言">
              {(['zh', 'en'] as const).map((value) => (
                <button key={value} type="button" aria-pressed={lang === value} onClick={() => setLang(value)} className={`min-h-11 rounded-md px-4 text-sm font-medium ${lang === value ? 'bg-secondary text-secondary-foreground' : 'text-muted-foreground hover:text-foreground'}`}>
                  {value === 'zh' ? '中文' : 'English'}
                </button>
              ))}
            </div>
          </div>
        </section>

        {user && capabilities.features.accounts.enabled && <PersonalApiKeySettings key={user.id} userId={user.id} />}

        {canManageChatGPT && <section aria-labelledby="account-settings" className="rounded-2xl border border-border bg-card p-5 sm:p-6">
          <h2 id="account-settings" className="text-lg font-semibold">账号与连接</h2>
          <p className="mt-1 text-sm text-muted-foreground">ChatGPT 订阅连接只属于当前 NewsHub 用户。</p>
          <div className="mt-5 flex flex-col gap-4 rounded-xl bg-muted/50 p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex gap-3">
              <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-background text-orange-600"><Bot aria-hidden="true" className="size-5" /></span>
              <div>
                <h3 className="font-medium">ChatGPT 订阅</h3>
                <p className="mt-1 text-sm text-muted-foreground">{user ? '连接账号、选择模型并确认翻译可用状态。' : '登录后可管理订阅连接。'}</p>
              </div>
            </div>
            <Button variant="outline" className="h-11" asChild>
              <Link to="/settings/chatgpt">{user ? '管理连接' : '查看说明'}</Link>
            </Button>
          </div>
        </section>}

        {(canCompareProviders || canManageAdmin) && <section aria-labelledby="tool-settings" className="rounded-2xl border border-border bg-card p-5 sm:p-6">
          <h2 id="tool-settings" className="text-lg font-semibold">站点工具</h2>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {canCompareProviders && <Button variant="outline" className="h-12 justify-start" asChild>
              <Link to="/provider-comparisons"><GitCompareArrows aria-hidden="true" />Provider 对比</Link>
            </Button>}
            {canManageAdmin && <Button variant="outline" className="h-12 justify-start" asChild>
              <a href="/admin" target="_blank" rel="noreferrer"><LockKeyhole aria-hidden="true" />{t.admin}</a>
            </Button>}
          </div>
        </section>}
      </div>
    </section>
  )
}
