import { useEffect, useState, type ReactNode } from 'react'
import type { PrivateTranslationTask } from '@/services/privateTranslationApi'
import { Check, Copy, Languages, Loader2, RefreshCw, XCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import type { NewsDetail } from '@/types/news'
import { hasReadableFullContent } from '@/types/news'
import MarkdownContent from './MarkdownContent'
import StreamingMarkdown from './StreamingMarkdown'
import ErrorBanner from './ErrorBanner'

interface FullContentSectionProps {
  news: NewsDetail
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
  translationActionLabel?: string
  translationControls?: ReactNode
  privateTask?: PrivateTranslationTask | null
  selectedPrivateResultId?: number | null
  onSelectPrivateResult?: (resultId: number | null) => void
}

export default function FullContentSection({
  news,
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
  translationActionLabel,
  translationControls,
  privateTask,
  selectedPrivateResultId = null,
  onSelectPrivateResult,
}: FullContentSectionProps) {
  if (!hasReadableFullContent(news)) return null
  const privateHistory = news.full_content_zh_private_history ?? []
  const hasHistory = privateHistory.length > 1 || privateHistory.some(item => !item.current_match)
  const selectedPrivate = privateHistory.find((item) => item.result_id === selectedPrivateResultId) ?? null
  const livePrivate = !showOriginal && !selectedPrivate && privateTask
  const content = livePrivate && ['queued', 'running'].includes(livePrivate.status) ? livePrivate.progress : showOriginal ? news.full_content : (selectedPrivate ? selectedPrivate.content : (livePrivate && livePrivate.status === 'succeeded' && livePrivate.result ? livePrivate.result.content : (news.full_content_zh || news.full_content)))
  const readingTranslation = !showOriginal && (selectedPrivate !== null || Boolean(privateTask?.result) || Boolean(news.full_content_zh))
  const legacyCodeRepair = readingTranslation
    ? selectedPrivate === null && news.full_content_zh_scope === 'legacy'
    : news.full_content_state === 'legacy'
  return (
    <div className="mb-8">
      <Toolbar
        news={news}
        content={content}
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
        translationActionLabel={translationActionLabel}
        translationControls={translationControls}
        selectedPrivateTranslation={Boolean(selectedPrivate || privateTask)}
      />

      {hasHistory ? (
        <details className="mb-4 text-sm text-muted-foreground">
          <summary className="cursor-pointer">历史译文</summary>
          <label htmlFor="saved-private-translation" className="mb-2 block text-sm font-medium">选择历史译文</label>
          <select
            id="saved-private-translation"
            aria-label="选择历史译文"
            className="h-10 max-w-full rounded-md border border-input bg-background px-3 text-sm"
            value={selectedPrivateResultId ?? ''}
            onChange={(event) => onSelectPrivateResult?.(event.target.value ? Number(event.target.value) : null)}
          >
            <option value="">当前译文</option>
            {privateHistory.map((item, index) => (
              <option key={item.result_id} value={item.result_id}>
                版本 {privateHistory.length - index} · {item.current_match ? '当前原文' : '旧版原文'}
              </option>
            ))}
          </select>
        </details>
      ) : null}
      {selectedPrivate && !selectedPrivate.current_match && !showOriginal && (
        <p role="status" className="mb-4 text-sm text-amber-700">
          这是原文更新前的译文。对应原文标题：{selectedPrivate.source_title || '标题不可用'}。
          在历史译文中选择“当前译文”可返回当前版本。
        </p>
      )}

      {allowTranslation && translating && <TranslationProgressUI progress={translationProgress} waitingShared={translationWaitingShared} onStop={onStopTranslation} />}
      {allowTranslation && translationPaused && !translating && !translateError && (
        <TranslationPausedUI onResume={onResumeTranslation} />
      )}
      {allowTranslation && translateError && <ErrorBanner message={translateError} onRetry={onRetryTranslate} />}

      <Card className="article-section-render py-5">
        <CardContent className="px-5">
          {livePrivate && ['queued', 'running'].includes(livePrivate.status)
            ? <div aria-label="正在生成的译文"><p role="status" className="mb-3 text-sm text-muted-foreground">翻译中，以下内容尚未完成。</p>
                {livePrivate.progress ? <StreamingMarkdown content={livePrivate.progress} /> : <p className="text-sm text-muted-foreground">正在等待模型响应…</p>}</div>
            : <MarkdownContent content={content} legacyCodeRepair={legacyCodeRepair} />}
        </CardContent>
      </Card>
    </div>
  )
}

type ToolbarProps = Pick<FullContentSectionProps, 'news' | 'translating' | 'translationPaused' | 'translateError' | 'showOriginal' | 'onToggleOriginal' | 'onTranslate' | 'onRefetch' | 'refetching' | 'onCancelRefetch' | 'allowFetch' | 'allowTranslation' | 'translationActionLabel' | 'translationControls'> & { selectedPrivateTranslation: boolean; content: string }

function Toolbar({ news, content, translating, translationPaused, translateError, showOriginal, onToggleOriginal, onTranslate, onRefetch, refetching, onCancelRefetch, allowFetch = true, allowTranslation = true, translationActionLabel, translationControls, selectedPrivateTranslation }: ToolbarProps) {
  const [copied, setCopied] = useState(false)
  const [copyMessage, setCopyMessage] = useState('')
  const [copyTimer, setCopyTimer] = useState<ReturnType<typeof setTimeout> | null>(null)

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
    <section aria-label="正文状态与操作" className="mb-4 flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <CopyButton copied={copied} onCopy={() => { void handleCopy() }} />
          {allowFetch && <RefetchButton refetching={refetching} onClick={onRefetch} onCancel={onCancelRefetch} />}
          {(news.full_content_zh || selectedPrivateTranslation) && <LangToggle showOriginal={showOriginal} onToggle={onToggleOriginal} />}
          {allowTranslation && !translationControls && !isChineseSource && !translating && !translationPaused && !translateError && (news.full_content_zh_scope !== 'shared' || news.full_translation_personal_available) && (
            <TranslateButton hasTranslation={Boolean(news.full_content_zh)} shared={news.full_content_zh_scope === 'shared'} onClick={onTranslate} actionLabel={translationActionLabel} />
          )}
          {allowTranslation && translationControls}
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
      className="h-10 rounded-full bg-secondary p-1"
    >
      <ToggleGroupItem value="zh" variant="default" size="pill" aria-label="切换中文" className="h-8 rounded-full border-0 px-3 text-xs data-[state=on]:bg-card data-[state=on]:text-foreground data-[state=on]:shadow-sm">中文</ToggleGroupItem>
      <ToggleGroupItem value="en" variant="default" size="pill" aria-label="切换英文" className="h-8 rounded-full border-0 px-3 text-xs data-[state=on]:bg-card data-[state=on]:text-foreground data-[state=on]:shadow-sm">EN</ToggleGroupItem>
    </ToggleGroup>
  )
}

function TranslateButton({ hasTranslation, shared, onClick, actionLabel }: { hasTranslation: boolean; shared: boolean; onClick: () => void; actionLabel?: string }) {
  const label = actionLabel ?? (shared ? '重新翻译' : hasTranslation ? '重新翻译' : '翻译为中文')
  return (
    <Button
      type="button"
      onClick={onClick}
      aria-label={label}
      variant={hasTranslation ? 'outline' : 'default'}
      size="pill-sm"
      className={hasTranslation ? 'h-10 rounded-full border-border px-3 text-xs font-medium text-muted-foreground hover:border-border hover:text-foreground' : 'h-10 rounded-full px-3'}
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
    <Button type="button" variant="outline" size="sm" onClick={onStop} aria-label="取消全文翻译" className="mt-3 h-7 rounded-full border-border px-2.5 text-[11px] text-primary">
      取消翻译
    </Button>
  )
  if (!progress) {
    return (
      <Card className="mb-6 items-center border-border bg-primary/10 py-8 text-center">
        <Loader2 className="size-7 animate-spin text-primary" />
        <div>
          <p className="mt-1 text-sm font-medium text-primary">{waitingShared ? '共享译文正在生成，完成后自动显示…' : '正在翻译全文…'}</p>
          <p className="mt-1 text-xs text-primary">{waitingShared ? '正在复用其他读者发起的翻译，不会显示其他用户的私有进度。' : '取消会阻止后续请求与保存；正在进行的请求可能先完成。'}</p>
          {stopButton}
        </div>
      </Card>
    )
  }
  return (
    <div className="mb-6">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Loader2 className="size-3.5 animate-spin text-primary" />
        <span className="text-xs font-medium text-primary">AI 正在翻译…</span>
        {stopButton}
        <span className="sr-only">取消会阻止后续请求与保存；正在进行的请求可能先完成。</span>
      </div>
      <Card className="border-border py-5 opacity-80">
        <CardContent className="px-5">
          <StreamingMarkdown content={progress} />
        </CardContent>
      </Card>
    </div>
  )
}

function TranslationPausedUI({ onResume }: { onResume: () => void }) {
  return (
    <Card className="mb-6 border-border bg-primary/10 p-4">
      <p className="text-sm text-primary">本页已停止接收更新，服务端翻译可能仍在继续。</p>
      <Button type="button" variant="outline" size="sm" onClick={onResume} className="mt-2 rounded-full border-border text-primary">
        继续接收翻译进度
      </Button>
    </Card>
  )
}
