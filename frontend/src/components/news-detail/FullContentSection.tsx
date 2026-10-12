import { useEffect, useState } from 'react'
import { Check, CheckCircle2, Copy, Languages, Loader2, RefreshCw, XCircle } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import type { NewsDetail } from '@/types/news'
import type { PrivateTranslationResult } from '@/services/newsWorkflowApi'
import MarkdownContent from './MarkdownContent'
import ErrorBanner from './ErrorBanner'

interface FullContentSectionProps {
  news: NewsDetail
  currentTranslation?: { text: string; resultId: string | null; scope: 'private' | 'shared' | 'legacy' } | null
  translating: boolean
  translationWaitingShared?: boolean
  translationPaused: boolean
  translateError: string
  translationProgress: string
  showOriginal: boolean
  onToggleOriginal: (showOriginal: boolean) => void
  onTranslate: () => void
  onRetryTranslate: () => void
  onResumeTranslation: () => void
  onStopTranslation: () => void
  onRefetch: () => void
  refetching: boolean
  onCancelRefetch: () => void
  allowFetch?: boolean
  allowTranslation?: boolean
  allowPrivateTranslation?: boolean
  privateTranslationActive?: boolean
  privateTranslationCancelPending?: boolean
  privateTranslationError?: string
  privateTranslationProgress?: string
  privateTranslationResult?: string
  privateTranslationResultId?: string
  privateTranslationResultCurrentMatch?: boolean | null
  privateTranslationStaleResult?: PrivateTranslationResult | null
  privateTranslationJobId?: string
  onStartPrivateTranslation?: () => void
  onCheckPrivateTranslationStatus?: () => void
  onCancelPrivateTranslation?: () => void
}

export default function FullContentSection({
  news,
  currentTranslation = null,
  translating,
  translationWaitingShared = false,
  translationPaused,
  translateError,
  translationProgress,
  showOriginal,
  onToggleOriginal,
  onTranslate,
  onRetryTranslate,
  onResumeTranslation,
  onStopTranslation,
  onRefetch,
  refetching,
  onCancelRefetch,
  allowFetch = true,
  allowTranslation = true,
  allowPrivateTranslation = false,
  privateTranslationActive = false,
  privateTranslationCancelPending = false,
  privateTranslationError = '',
  privateTranslationProgress = '',
  privateTranslationResult = '',
  privateTranslationResultId = '',
  privateTranslationResultCurrentMatch = null,
  privateTranslationStaleResult = null,
  privateTranslationJobId = '',
  onStartPrivateTranslation = () => {},
  onCheckPrivateTranslationStatus = () => {},
  onCancelPrivateTranslation = () => {},
}: FullContentSectionProps) {
  const currentText = currentTranslation?.text
    || (news.full_content_zh_current_match === false ? '' : news.full_content_zh)
  const resolvedCurrentTranslation = currentTranslation ?? (currentText
    ? {
        text: currentText,
        resultId: news.full_content_zh_result_id || null,
        scope: news.full_content_zh_scope === 'private' ? 'private' as const : news.full_content_zh_scope === 'shared' ? 'shared' as const : 'legacy' as const,
      }
    : null)
  const content = showOriginal ? news.full_content : (currentText || news.full_content)
  const privateTranslationNeedsPreference = privateTranslationError === '请先在 AI 设置中为“全文翻译”选择个人模型。'
  return (
    <div className="mb-8">
      <Toolbar
        news={news}
        currentTranslation={resolvedCurrentTranslation}
        hasCurrentTranslation={Boolean(currentText)}
        translating={translating}
        translationPaused={translationPaused}
        translateError={translateError}
        showOriginal={showOriginal}
        onToggleOriginal={onToggleOriginal}
        onTranslate={onTranslate}
        onRefetch={onRefetch}
        refetching={refetching}
        onCancelRefetch={onCancelRefetch}
        allowFetch={allowFetch}
        allowTranslation={allowTranslation}
        allowPrivateTranslation={allowPrivateTranslation}
        privateTranslationActive={privateTranslationActive}
        hasPrivateTranslation={Boolean(privateTranslationResult && privateTranslationResultCurrentMatch !== false)}
        onStartPrivateTranslation={onStartPrivateTranslation}
      />

      {allowTranslation && translating && <TranslationProgressUI progress={translationProgress} waitingShared={translationWaitingShared} onStop={onStopTranslation} />}
      {allowTranslation && translationPaused && !translating && !translateError && (
        <TranslationPausedUI onResume={onResumeTranslation} />
      )}
      {allowTranslation && translateError && (
        <section aria-label="站点翻译错误" className="mb-6">
          <p className="mb-1 text-xs font-semibold text-red-700">站点翻译</p>
          <ErrorBanner message={translateError} onRetry={onRetryTranslate} />
        </section>
      )}

      {allowPrivateTranslation && privateTranslationActive && (
        <section aria-label="个人模型翻译进度" className="mb-6 rounded-xl border border-violet-100 bg-violet-50/60 p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p role="status" className="text-sm font-medium text-violet-800">个人模型正在翻译，进度和结果仅你可见。</p>
              {privateTranslationProgress && <pre className="mt-3 max-h-64 overflow-auto whitespace-pre-wrap break-words text-xs leading-5 text-violet-900">{privateTranslationProgress}</pre>}
            </div>
            <div className="flex shrink-0 flex-wrap gap-2">
              <Button type="button" variant="outline" size="sm" onClick={onCheckPrivateTranslationStatus} disabled={!privateTranslationJobId} className="rounded-full">
                重新检查状态
              </Button>
              <Button type="button" variant="outline" size="sm" onClick={onCancelPrivateTranslation} disabled={!privateTranslationJobId} className="rounded-full">
                {privateTranslationCancelPending ? '再次取消' : '取消任务'}
              </Button>
            </div>
          </div>
        </section>
      )}
      {allowPrivateTranslation && privateTranslationError && (
        <div role="alert" aria-label="个人模型翻译错误" className="mb-6 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <p className="font-semibold">个人模型翻译</p>
          {privateTranslationNeedsPreference ? (
            <>
              <p className="mt-1">尚未为个人模型翻译选择用途模型，本次任务未启动。</p>
              <p className="mt-2">
                <a href="/settings/ai" className="font-medium underline underline-offset-2">打开 AI 设置</a>
                ，在“用途偏好”中为“全文翻译”选择模型，或选择“跟随默认”，然后点击“保存用途偏好”。
              </p>
              <p className="mt-1 text-xs">添加连接、添加模型或测试模型都不会自动更改用途选择。</p>
            </>
          ) : <p className="mt-1">{privateTranslationError}</p>}
        </div>
      )}
      {allowPrivateTranslation && privateTranslationResult && privateTranslationResultCurrentMatch !== false
        && privateTranslationResultId !== resolvedCurrentTranslation?.resultId &&
        privateTranslationResultId !== news.full_content_zh_result_id && (
        <Card className="mb-6 border-violet-200 bg-violet-50/30 py-5">
          <CardContent className="px-5">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="text-sm font-semibold text-violet-900">个人模型译文 · 仅你可见</p>
                <p className="mt-1 text-xs text-violet-700">通过个人 API Key 生成，不会发布为共享译文。</p>
              </div>
              {privateTranslationResultId && <span className="text-[11px] text-muted-foreground">结果 {privateTranslationResultId.slice(0, 8)}</span>}
            </div>
            <MarkdownContent content={privateTranslationResult} />
          </CardContent>
        </Card>
      )}
      {resolvedCurrentTranslation?.scope === 'private' && (
        <p className="mb-4 text-xs text-violet-700">当前正文来自你的个人模型译文，只对你可见，不会作为共享译文发布。</p>
      )}
      {allowPrivateTranslation && privateTranslationStaleResult && (
        <Card className="mb-6 border-amber-200 bg-amber-50/40 py-5">
          <CardContent className="px-5">
            <details>
              <summary className="cursor-pointer text-sm font-semibold text-amber-900">
                上一版个人译文 · 原文已更新（{privateTranslationStaleResult.modelSource?.model || '已保存结果'}）
              </summary>
              <p className="mt-2 text-xs text-amber-800">这份结果仍保存在你的账号中，但它对应旧版原文，详情、问答和朗读不会将它当作当前译文。</p>
              <div className="mt-4"><MarkdownContent content={privateTranslationStaleResult.text} /></div>
            </details>
          </CardContent>
        </Card>
      )}

      <Card className="article-section-render py-5">
        <CardContent className="px-5">
          <MarkdownContent content={content} />
        </CardContent>
      </Card>
    </div>
  )
}

type ToolbarProps = Pick<FullContentSectionProps, 'news' | 'currentTranslation' | 'translating' | 'translationPaused' | 'translateError' | 'showOriginal' | 'onToggleOriginal' | 'onTranslate' | 'onRefetch' | 'refetching' | 'onCancelRefetch' | 'allowFetch' | 'allowTranslation' | 'allowPrivateTranslation' | 'privateTranslationActive' | 'onStartPrivateTranslation'> & { hasPrivateTranslation: boolean; hasCurrentTranslation: boolean }

function Toolbar({ news, currentTranslation = null, translating, translationPaused, translateError, showOriginal, onToggleOriginal, onTranslate, onRefetch, refetching, onCancelRefetch, allowFetch = true, allowTranslation = true, allowPrivateTranslation = false, privateTranslationActive = false, hasPrivateTranslation, hasCurrentTranslation, onStartPrivateTranslation = () => {} }: ToolbarProps) {
  const [copied, setCopied] = useState(false)
  const [copyMessage, setCopyMessage] = useState('')
  const [copyTimer, setCopyTimer] = useState<ReturnType<typeof setTimeout> | null>(null)
  const content = showOriginal ? news.full_content : (currentTranslation?.text || (news.full_content_zh_current_match === false ? '' : news.full_content_zh) || news.full_content)

  useEffect(() => () => { if (copyTimer) clearTimeout(copyTimer) }, [copyTimer])

  async function handleCopy() {
    if (!content) return
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
      setCopyMessage('已复制全文')
      if (copyTimer) clearTimeout(copyTimer)
      setCopyTimer(setTimeout(() => {
        setCopied(false)
        setCopyMessage('')
        setCopyTimer(null)
      }, 2000))
    } catch {
      setCopyMessage('复制失败，请检查浏览器剪贴板权限')
    }
  }

  const isChineseSource = news.source_language === 'zh'

  return (
    <section aria-label="正文状态与操作" className="mb-5 rounded-xl border border-border bg-secondary/50 p-3 sm:p-4 backdrop-blur-xs">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge variant="green" className="rounded-full px-2.5 py-0.5 text-[11px] font-medium">
              <CheckCircle2 className="size-3" />正文已就绪
            </Badge>
            {hasCurrentTranslation && !isChineseSource && (
              <Badge variant="violet" className="rounded-full px-2.5 py-0.5 text-[11px] font-medium">
                <Languages className="size-3" />{currentTranslation?.scope === 'shared' ? '共享译文' : currentTranslation?.scope === 'private' ? '个人译文' : '已有中文译文'}
              </Badge>
            )}
            {currentTranslation?.resultId === news.full_content_zh_result_id && news.full_content_zh_model_source?.model && (
              <Badge variant="secondary" className="rounded-full px-2.5 py-0.5 text-[11px] font-medium">
                {news.full_content_zh_model_source.model}
              </Badge>
            )}
            {!hasCurrentTranslation && news.full_content_zh_current_match === false && (
              <Badge variant="outline" className="rounded-full px-2.5 py-0.5 text-[11px] font-medium text-amber-800">原文已更新</Badge>
            )}
          </div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            {isChineseSource
              ? allowFetch ? '正文排版已就绪，可复制或重新获取。' : '正文排版已就绪，可复制。'
              : currentTranslation?.scope === 'private'
                ? '这是当前账号的个人译文，重新翻译不会覆盖共享版本。'
                : currentTranslation?.scope === 'shared'
                  ? allowTranslation ? '正在复用共享译文，不消耗你的模型额度。个人重新翻译会使用你的账号额度。' : '正在复用共享译文。'
                  : allowFetch && allowTranslation
                    ? '正文结构已保留，可复制、重新获取或翻译。首次完整翻译后可供其他读者复用。'
                    : '正文结构已保留，可复制或切换已缓存的语言。'}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <CopyButton copied={copied} onCopy={() => { void handleCopy() }} />
          {allowFetch && <RefetchButton refetching={refetching} onClick={onRefetch} onCancel={onCancelRefetch} />}
          {hasCurrentTranslation && <LangToggle showOriginal={showOriginal} onToggle={onToggleOriginal} />}
          {allowTranslation && !isChineseSource && !translating && !translationPaused && !translateError && (currentTranslation?.scope !== 'shared' || news.full_translation_personal_available) && (
            <TranslateButton hasTranslation={hasCurrentTranslation} shared={currentTranslation?.scope === 'shared'} onClick={onTranslate} />
          )}
          {allowPrivateTranslation && !isChineseSource && !translating && !translationPaused && !privateTranslationActive && (
            <Button type="button" onClick={onStartPrivateTranslation} variant="outline" size="pill-sm" className="h-10 rounded-full border-violet-200 px-3 text-xs font-medium text-violet-800 hover:bg-violet-50">
              <Languages className="size-3" />{hasPrivateTranslation ? '重新生成个人译文' : '使用个人模型翻译'}
            </Button>
          )}
          {allowPrivateTranslation && privateTranslationActive && (
            <Button type="button" disabled variant="outline" size="pill-sm" className="h-10 rounded-full px-3 text-xs">
              <Loader2 className="size-3 animate-spin" />正在翻译个人译文
            </Button>
          )}
        </div>
      </div>
      {copyMessage && <span role="status" className="sr-only">{copyMessage}</span>}
    </section>
  )
}

function LangToggle({ showOriginal, onToggle }: { showOriginal: boolean; onToggle: (value: boolean) => void }) {
  return (
    <ToggleGroup
      type="single"
      value={showOriginal ? 'en' : 'zh'}
      onValueChange={(value: string) => { if (value) onToggle(value === 'en') }}
      variant="default"
      size="pill"
      aria-label="切换语言"
      className="h-10 rounded-full bg-neutral-100 p-1"
    >
      <ToggleGroupItem value="zh" variant="default" size="pill" aria-label="切换中文" className="h-8 rounded-full border-0 px-3 text-xs data-[state=on]:bg-white data-[state=on]:text-neutral-900 data-[state=on]:shadow-sm">中文</ToggleGroupItem>
      <ToggleGroupItem value="en" variant="default" size="pill" aria-label="切换英文" className="h-8 rounded-full border-0 px-3 text-xs data-[state=on]:bg-white data-[state=on]:text-neutral-900 data-[state=on]:shadow-sm">EN</ToggleGroupItem>
    </ToggleGroup>
  )
}

function TranslateButton({ hasTranslation, shared, onClick }: { hasTranslation: boolean; shared: boolean; onClick: () => void }) {
  const label = shared ? '生成个人译文' : hasTranslation ? '重新翻译' : '翻译为中文'
  return (
    <Button
      type="button"
      onClick={onClick}
      aria-label={label}
      variant={hasTranslation ? 'outline' : 'violet'}
      size="pill-sm"
      className={hasTranslation ? 'h-10 rounded-full border-neutral-200 px-3 text-xs font-medium text-neutral-600 hover:border-neutral-300 hover:text-neutral-900' : 'h-10 rounded-full px-3'}
    >
      <Languages className="size-3" />{label}
    </Button>
  )
}

function RefetchButton({ refetching, onClick, onCancel }: { refetching: boolean; onClick: () => void; onCancel: () => void }) {
  return refetching ? (
    <Button type="button" variant="outline" size="sm" onClick={onCancel} aria-label="取消获取原文" className="h-10 rounded-full px-3 text-xs">
      <XCircle className="size-3" />取消
    </Button>
  ) : (
    <Button type="button" variant="outline" size="sm" onClick={onClick} aria-label="重新获取原文" className="h-10 rounded-full px-3 text-xs">
      <RefreshCw className="size-3" />重新获取原文
    </Button>
  )
}

function CopyButton({ copied, onCopy }: { copied: boolean; onCopy: () => void }) {
  return (
    <Button type="button" variant="outline" size="sm" onClick={onCopy} aria-label="复制全文" className="h-10 rounded-full px-3 text-xs">
      {copied ? <><Check className="size-3" />已复制</> : <><Copy className="size-3" />复制全文</>}
    </Button>
  )
}

function TranslationProgressUI({ progress, waitingShared, onStop }: { progress: string; waitingShared: boolean; onStop: () => void }) {
  const stopButton = (
    <Button type="button" variant="outline" size="sm" onClick={onStop} aria-label="取消全文翻译" className="mt-3 h-7 rounded-full border-violet-200 px-2.5 text-[11px] text-violet-700">
      取消翻译
    </Button>
  )
  if (!progress) {
    return (
      <Card className="mb-6 items-center border-violet-100 bg-violet-50/60 py-8 text-center">
        <Loader2 className="size-7 animate-spin text-violet-500" />
        <div>
          <p className="mt-1 text-sm font-medium text-violet-700">{waitingShared ? '共享译文正在生成，完成后自动显示…' : '正在翻译全文…'}</p>
          <p className="mt-1 text-xs text-violet-500">{waitingShared ? '正在复用其他读者发起的翻译，不会显示其他用户的私有进度。' : '取消会阻止后续请求与保存；正在进行的请求可能先完成。'}</p>
          {stopButton}
        </div>
      </Card>
    )
  }
  return (
    <div className="mb-6">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Loader2 className="size-3.5 animate-spin text-violet-500" />
        <span className="text-xs font-medium text-violet-500">AI 正在翻译…</span>
        {stopButton}
        <span className="sr-only">取消会阻止后续请求与保存；正在进行的请求可能先完成。</span>
      </div>
      <Card className="border-violet-100 py-5 opacity-80">
        <CardContent className="px-5">
          <div className="article-markdown prose prose-gray max-w-none"><MarkdownContent content={progress} /></div>
        </CardContent>
      </Card>
    </div>
  )
}

function TranslationPausedUI({ onResume }: { onResume: () => void }) {
  return (
    <Card className="mb-6 border-violet-100 bg-violet-50/60 p-4">
      <p className="text-sm text-violet-800">本页已停止接收更新，服务端翻译可能仍在继续。</p>
      <Button type="button" variant="outline" size="sm" onClick={onResume} className="mt-2 rounded-full border-violet-200 text-violet-700">
        继续接收翻译进度
      </Button>
    </Card>
  )
}
