import { Languages, Loader2, CheckCircle2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import MarkdownContent from './MarkdownContent'
import ErrorBanner from './ErrorBanner'

/**
 * FullContentSection — toolbar + content panel for the article's full body.
 *
 * Owns three small sub-components (LangToggle / TranslateButton /
 * TranslationProgressUI) that are only meaningful in this context.
 *
 * Props:
 *   news                  — current news object (must have full_content; full_content_zh optional)
 *   translating           — boolean, true while SSE stream is open
 *   translateError        — string | '' — error message from last attempt
 *   translationProgress   — string — incremental markdown being streamed in
 *   showOriginal          — boolean — true when user wants English source visible
 *   onToggleOriginal      — (bool) => void
 *   onTranslate           — () => void   — invoked for fresh translate / attach
 *   onRetryTranslate      — () => void   — invoked after translateError
 */
export default function FullContentSection({
  news, translating, translateError, translationProgress,
  showOriginal, onToggleOriginal, onTranslate, onRetryTranslate,
}) {
  return (
    <div className="mb-6">
      <Toolbar
        news={news}
        translating={translating}
        translateError={translateError}
        showOriginal={showOriginal}
        onToggleOriginal={onToggleOriginal}
        onTranslate={onTranslate}
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

function Toolbar({ news, translating, translateError, showOriginal, onToggleOriginal, onTranslate }) {
  return (
    <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
      <div className="flex items-center gap-2">
        <Badge variant="green">
          <CheckCircle2 />
          原文已加载
        </Badge>
        {news.full_content_zh && (
          <Badge variant="violet">
            <Languages />
            已翻译
          </Badge>
        )}
      </div>
      <div className="flex items-center gap-2">
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
  // shadcn ToggleGroup ('single' type) gives us proper radiogroup semantics +
  // aria-pressed via Radix. Value is a string ('zh' | 'en').
  return (
    <ToggleGroup
      type="single"
      value={showOriginal ? 'en' : 'zh'}
      onValueChange={(v) => {
        // Radix emits '' when the user clicks the active item — guard so we
        // don't accidentally clear the selection.
        if (v) onToggle(v === 'en')
      }}
      size="pill"
      aria-label="切换语言"
      className="bg-gray-100 p-0.5 rounded-full"
    >
      <ToggleGroupItem value="zh" aria-label="切换中文" className="border-0">中文</ToggleGroupItem>
      <ToggleGroupItem value="en" aria-label="切换英文" className="border-0">English</ToggleGroupItem>
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
    >
      <Languages className="size-3.5" />
      {hasTranslation ? '重新翻译' : '翻译为中文'}
    </Button>
  )
}

function TranslationProgressUI({ progress }) {
  // No progress yet — show centred spinner card
  if (!progress) {
    return (
      <Card className="mb-6 py-8 bg-violet-50 border-violet-200 items-center text-center">
        <Loader2 className="size-8 text-violet-500 animate-spin" />
        <div>
          <p className="text-sm text-violet-600 font-medium">正在使用 AI 翻译...</p>
          <p className="text-xs text-violet-400 mt-1">通义千问大模型，翻译准确自然</p>
        </div>
      </Card>
    )
  }
  // Streaming progress — show partial markdown
  return (
    <div className="mb-6">
      <div className="flex items-center gap-2 mb-3">
        <Loader2 className="size-4 text-violet-500 animate-spin" />
        <span className="text-xs text-violet-500 font-medium">AI 正在翻译...</span>
      </div>
      <Card className="border-violet-200 py-5 opacity-80">
        <CardContent className="px-5">
          <div className="article-markdown prose prose-gray max-w-none">
            <MarkdownContent content={progress} />
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
