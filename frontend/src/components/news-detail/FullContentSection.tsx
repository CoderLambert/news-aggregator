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

      <Card className="py-5">
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

  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-1.5">
        <Badge variant="green" className="rounded-full px-2.5 py-0.5 text-[11px] font-medium">
          <CheckCircle2 className="size-3" />原文已加载
        </Badge>
        {news.full_content_zh && (
          <Badge variant="violet" className="rounded-full px-2.5 py-0.5 text-[11px] font-medium">
            <Languages className="size-3" />已翻译
          </Badge>
        )}
      </div>

      <div className="flex items-center gap-2">
        <CopyButton copied={copied} onCopy={() => { void handleCopy() }} />
        <RefetchButton refetching={refetching} onClick={onRefetch} onCancel={onCancelRefetch} />
        {news.full_content_zh && <LangToggle showOriginal={showOriginal} onToggle={onToggleOriginal} />}
        {!translating && !translationPaused && !translateError && (
          <TranslateButton hasTranslation={Boolean(news.full_content_zh)} onClick={onTranslate} />
        )}
      </div>
      {copyMessage && <span role="status" className="sr-only">{copyMessage}</span>}
    </div>
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
      className="rounded-full bg-neutral-100 p-0.5"
    >
      <ToggleGroupItem value="zh" variant="default" size="pill" aria-label="切换中文" className="h-6 rounded-full border-0 px-2.5 text-xs data-[state=on]:bg-white data-[state=on]:text-neutral-900 data-[state=on]:shadow-sm">中文</ToggleGroupItem>
      <ToggleGroupItem value="en" variant="default" size="pill" aria-label="切换英文" className="h-6 rounded-full border-0 px-2.5 text-xs data-[state=on]:bg-white data-[state=on]:text-neutral-900 data-[state=on]:shadow-sm">EN</ToggleGroupItem>
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
      className={hasTranslation ? 'h-7 rounded-full border-neutral-200 text-[11px] font-medium text-neutral-600 hover:border-neutral-300 hover:text-neutral-900' : 'rounded-full'}
    >
      <Languages className="size-3" />{hasTranslation ? '重新翻译' : '翻译为中文'}
    </Button>
  )
}

function RefetchButton({ refetching, onClick, onCancel }: { refetching: boolean; onClick: () => void; onCancel: () => void }) {
  return refetching ? (
    <Button type="button" variant="outline" size="sm" onClick={onCancel} aria-label="取消获取原文" className="h-7 rounded-full px-2.5 text-[11px]">
      <XCircle className="size-3" />取消
    </Button>
  ) : (
    <Button type="button" variant="outline" size="sm" onClick={onClick} aria-label="重新获取原文" className="h-7 rounded-full px-2.5 text-[11px]">
      <RefreshCw className="size-3" />重新获取原文
    </Button>
  )
}

function CopyButton({ copied, onCopy }: { copied: boolean; onCopy: () => void }) {
  return (
    <Button type="button" variant="outline" size="sm" onClick={onCopy} aria-label="复制全文" className="h-7 rounded-full px-2.5 text-[11px]">
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
