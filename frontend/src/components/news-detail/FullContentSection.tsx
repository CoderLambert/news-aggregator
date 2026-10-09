import { useEffect, useState } from 'react'
import { Check, CheckCircle2, Copy, Languages, Loader2, RefreshCw, XCircle } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import type { NewsDetail } from '@/types/news'
import MarkdownContent from './MarkdownContent'
import ErrorBanner from './ErrorBanner'

interface FullContentSectionProps {
  news: NewsDetail
  translating: boolean
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
}

export default function FullContentSection({
  news,
  translating,
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
}: FullContentSectionProps) {
  const content = showOriginal ? news.full_content : (news.full_content_zh || news.full_content)
  return (
    <div className="mb-8">
      <Toolbar
        news={news}
        translating={translating}
        translationPaused={translationPaused}
        translateError={translateError}
        showOriginal={showOriginal}
        onToggleOriginal={onToggleOriginal}
        onTranslate={onTranslate}
        onRefetch={onRefetch}
        refetching={refetching}
        onCancelRefetch={onCancelRefetch}
      />

      {translating && <TranslationProgressUI progress={translationProgress} onStop={onStopTranslation} />}
      {translationPaused && !translating && !translateError && (
        <TranslationPausedUI onResume={onResumeTranslation} />
      )}
      {translateError && <ErrorBanner message={translateError} onRetry={onRetryTranslate} />}

      <Card className="article-section-render py-5">
        <CardContent className="px-5">
          <MarkdownContent content={content} />
        </CardContent>
      </Card>
    </div>
  )
}

type ToolbarProps = Pick<FullContentSectionProps, 'news' | 'translating' | 'translationPaused' | 'translateError' | 'showOriginal' | 'onToggleOriginal' | 'onTranslate' | 'onRefetch' | 'refetching' | 'onCancelRefetch'>

function Toolbar({ news, translating, translationPaused, translateError, showOriginal, onToggleOriginal, onTranslate, onRefetch, refetching, onCancelRefetch }: ToolbarProps) {
  const [copied, setCopied] = useState(false)
  const [copyMessage, setCopyMessage] = useState('')
  const [copyTimer, setCopyTimer] = useState<ReturnType<typeof setTimeout> | null>(null)
  const content = showOriginal ? news.full_content : (news.full_content_zh || news.full_content)

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
            {news.full_content_zh && !isChineseSource && (
              <Badge variant="violet" className="rounded-full px-2.5 py-0.5 text-[11px] font-medium">
                <Languages className="size-3" />已有中文译文
              </Badge>
            )}
          </div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            {isChineseSource ? '正文排版已就绪，可复制或重新获取。' : '正文结构已保留，可复制、重新获取或翻译。'}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <CopyButton copied={copied} onCopy={() => { void handleCopy() }} />
          <RefetchButton refetching={refetching} onClick={onRefetch} onCancel={onCancelRefetch} />
          {news.full_content_zh && <LangToggle showOriginal={showOriginal} onToggle={onToggleOriginal} />}
          {!isChineseSource && !translating && !translationPaused && !translateError && (
            <TranslateButton hasTranslation={Boolean(news.full_content_zh)} onClick={onTranslate} />
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

function TranslateButton({ hasTranslation, onClick }: { hasTranslation: boolean; onClick: () => void }) {
  return (
    <Button
      type="button"
      onClick={onClick}
      aria-label={hasTranslation ? '重新翻译' : '翻译为中文'}
      variant={hasTranslation ? 'outline' : 'violet'}
      size="pill-sm"
      className={hasTranslation ? 'h-10 rounded-full border-neutral-200 px-3 text-xs font-medium text-neutral-600 hover:border-neutral-300 hover:text-neutral-900' : 'h-10 rounded-full px-3'}
    >
      <Languages className="size-3" />{hasTranslation ? '重新翻译' : '翻译为中文'}
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

function TranslationProgressUI({ progress, onStop }: { progress: string; onStop: () => void }) {
  const stopButton = (
    <Button type="button" variant="outline" size="sm" onClick={onStop} aria-label="停止接收翻译更新" className="mt-3 h-7 rounded-full border-violet-200 px-2.5 text-[11px] text-violet-700">
      停止接收
    </Button>
  )
  if (!progress) {
    return (
      <Card className="mb-6 items-center border-violet-100 bg-violet-50/60 py-8 text-center">
        <Loader2 className="size-7 animate-spin text-violet-500" />
        <div>
          <p className="text-sm font-medium text-violet-600">正在翻译全文…</p>
          <p className="mt-1 text-xs text-violet-500">停止接收只会关闭本页连接，服务端翻译仍会继续。</p>
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
        <span className="sr-only">停止接收只会关闭本页连接，服务端翻译仍会继续。</span>
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
