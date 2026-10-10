import type { LucideIcon } from 'lucide-react'
import { AlignLeft, ArrowLeft, Bot, Check, GitCompareArrows, Languages, LockKeyhole, Type } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/context/AuthContext'
import { useLanguage } from '@/context/useLanguage'
import type { DisplayMode } from '@/types/news'
import { useCapabilities } from '@/context/CapabilitiesContext'

const DISPLAY_MODES = [
  { key: 'zh', label: '中文', description: '优先显示中文内容', icon: Type },
  { key: 'original', label: '原文', description: '优先显示来源原文', icon: Languages },
  { key: 'bilingual', label: '双文', description: '中文与原文一起阅读', icon: AlignLeft },
] satisfies ReadonlyArray<{ key: DisplayMode; label: string; description: string; icon: LucideIcon }>

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
