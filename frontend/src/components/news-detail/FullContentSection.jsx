import { useState } from 'react'
import { Languages, Loader2, CheckCircle2, Copy, Check, RefreshCw, XCircle } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import MarkdownContent from './MarkdownContent'
import ErrorBanner from './ErrorBanner'

/**
 * FullContentSection — toolbar + content panel for the article's full body.
 */
export default function FullContentSection({
  news, translating, translateError, translationProgress,
  showOriginal, onToggleOriginal, onTranslate, onRetryTranslate,
  onRefetch, refetching, onCancelRefetch,
}) {
  return (
    <div className="mb-8">
      <Toolbar
        news={news}
        translating={translating}
        translateError={translateError}
        showOriginal={showOriginal}
        onToggleOriginal={onToggleOriginal}
        onTranslate={onTranslate}
        onRefetch={onRefetch}
        refetching={refetching}
        onCancelRefetch={onCancelRefetch}
      />

      {translating && <TranslationProgressUI progress={translationProgress} />}

      {translateError && <ErrorBanner message={translateError} onRetry={onRetryTranslate} />}

      <Card className="py-5">
        <CardContent className="px-5">
          <MarkdownContent content={showOriginal ? news.full_content : (news.full_content_zh || news.full_content)} />
        </CardContent>
      </Card>
    </div>
  )
}

/* ── Sub-components (private to FullContentSection) ────────────────────── */

function Toolbar({ news, translating, translateError, showOriginal, onToggleOriginal, onTranslate, onRefetch, refetching, onCancelRefetch }) {
  const [copied, setCopied] = useState(false)

  function handleCopy() {
    const content = showOriginal ? news.full_content : (news.full_content_zh || news.full_content)
    if (!content) return
    navigator.clipboard.writeText(content).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
      {/* Left: status badges */}
      <div className="flex items-center gap-1.5">
        <Badge variant="green" className="rounded-full px-2.5 py-0.5 text-[11px] font-medium">
          <CheckCircle2 className="size-3" />
          原文已加载
        </Badge>
        {news.full_content_zh && (
          <Badge variant="violet" className="rounded-full px-2.5 py-0.5 text-[11px] font-medium">
            <Languages className="size-3" />
            已翻译
          </Badge>
        )}
      </div>

      {/* Right: action controls */}
      <div className="flex items-center gap-2">
        <CopyButton copied={copied} onCopy={handleCopy} />
        <RefetchButton refetching={refetching} onClick={onRefetch} onCancel={onCancelRefetch} />
        {news.full_content_zh && (
          <LangToggle showOriginal={showOriginal} onToggle={onToggleOriginal} />
        )}
        {!translating && !translateError && (
          <TranslateButton hasTranslation={!!news.full_content_zh} onClick={onTranslate} />
        )}
      </div>
    </div>
  )
}

function LangToggle({ showOriginal, onToggle }) {
  return (
    <ToggleGroup
      type="single"
      value={showOriginal ? 'en' : 'zh'}
      onValueChange={(v) => {
        if (v) onToggle(v === 'en')
      }}
      size="pill"
      aria-label="切换语言"
      className="bg-neutral-100 p-0.5 rounded-full"
    >
      <ToggleGroupItem value="zh" aria-label="切换中文" className="border-0 text-xs h-6 px-2.5 rounded-full data-[state=on]:bg-white data-[state=on]:shadow-sm data-[state=on]:text-neutral-900 text-neutral-500">中文</ToggleGroupItem>
      <ToggleGroupItem value="en" aria-label="切换英文" className="border-0 text-xs h-6 px-2.5 rounded-full data-[state=on]:bg-white data-[state=on]:shadow-sm data-[state=on]:text-neutral-900 text-neutral-500">EN</ToggleGroupItem>
    </ToggleGroup>
  )
}

function TranslateButton({ hasTranslation, onClick }) {
  return (
    <Button
      type="button"
      onClick={onClick}
      aria-label={hasTranslation ? '重新翻译' : '翻译为中文'}
      variant={hasTranslation ? 'outline' : 'violet'}
      size="pill-sm"
      className={hasTranslation ? 'rounded-full h-7 text-[11px] font-medium border-neutral-200 text-neutral-600 hover:text-neutral-900 hover:border-neutral-300' : 'rounded-full'}
    >
      <Languages className="size-3" />
      {hasTranslation ? '重新翻译' : '翻译为中文'}
    </Button>
  )
}

function RefetchButton({ refetching, onClick, onCancel }) {
  if (refetching) {
    return (
      <button
        type="button"
        onClick={onCancel}
        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium
                   transition-all border cursor-pointer
                   bg-amber-50 border-amber-200 text-amber-600 hover:bg-amber-100"
      >
        <XCircle className="w-3 h-3" />
        取消
      </button>
    )
  }
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium
                   transition-all border cursor-pointer
                   bg-white border-neutral-200 text-neutral-500 hover:border-amber-200 hover:text-amber-600"
    >
      <RefreshCw className="w-3 h-3" />
      重新获取原文
    </button>
  )
}

function CopyButton({ copied, onCopy }) {
  return (
    <button
      type="button"
      onClick={onCopy}
      className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium
                   transition-all border cursor-pointer
                   ${copied
                     ? 'bg-emerald-50 border-emerald-200 text-emerald-600'
                     : 'bg-white border-neutral-200 text-neutral-500 hover:border-violet-200 hover:text-violet-600'
                   }`}
    >
      {copied ? (
        <>
          <Check className="w-3 h-3" />
          已复制
        </>
      ) : (
        <>
          <Copy className="w-3 h-3" />
          复制全文
        </>
      )}
    </button>
  )
}

function TranslationProgressUI({ progress }) {
  if (!progress) {
    return (
      <Card className="mb-6 py-8 bg-violet-50/60 border-violet-100 items-center text-center">
        <Loader2 className="size-7 text-violet-500 animate-spin" />
        <div>
          <p className="text-sm text-violet-600 font-medium">正在使用 AI 翻译...</p>
          <p className="text-xs text-violet-400 mt-1">大模型翻译，准确自然</p>
        </div>
      </Card>
    )
  }
  return (
    <div className="mb-6">
      <div className="flex items-center gap-2 mb-3">
        <Loader2 className="size-3.5 text-violet-500 animate-spin" />
        <span className="text-xs text-violet-500 font-medium">AI 正在翻译...</span>
      </div>
      <Card className="border-violet-100 py-5 opacity-80">
        <CardContent className="px-5">
          <div className="article-markdown prose prose-gray max-w-none">
            <MarkdownContent content={progress} />
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
