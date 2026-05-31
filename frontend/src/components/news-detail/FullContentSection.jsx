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

      <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
        <MarkdownContent content={showOriginal ? news.full_content : (news.full_content_zh || news.full_content)} />
      </div>
    </div>
  )
}

/* ── Sub-components (private to FullContentSection) ────────────────────── */

function Toolbar({ news, translating, translateError, showOriginal, onToggleOriginal, onTranslate }) {
  return (
    <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
      <div className="flex items-center gap-2">
        <span className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-green-50 text-green-700 border border-green-200">
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
          </svg>
          原文已加载
        </span>
        {news.full_content_zh && (
          <span className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-violet-50 text-violet-700 border border-violet-200">
            <TranslateIcon className="w-3 h-3" />
            已翻译
          </span>
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
  return (
    <div className="flex bg-gray-100 rounded-full p-0.5" role="group" aria-label="切换语言">
      <button
        type="button"
        onClick={() => onToggle(false)}
        aria-pressed={!showOriginal}
        aria-label="切换中文"
        className={`px-3 py-1 text-xs rounded-full transition-all ${
          !showOriginal ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
        }`}
      >中文</button>
      <button
        type="button"
        onClick={() => onToggle(true)}
        aria-pressed={showOriginal}
        aria-label="切换英文"
        className={`px-3 py-1 text-xs rounded-full transition-all ${
          showOriginal ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
        }`}
      >English</button>
    </div>
  )
}

function TranslateButton({ hasTranslation, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={hasTranslation ? '重新翻译' : '翻译为中文'}
      className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-full transition-all duration-200 shadow-sm hover:shadow
        ${hasTranslation
          ? 'bg-gray-100 text-gray-600 hover:bg-gray-200 border border-gray-200'
          : 'bg-violet-600 text-white hover:bg-violet-700'
        }`}
    >
      <TranslateIcon className="w-3.5 h-3.5" />
      {hasTranslation ? '重新翻译' : '翻译为中文'}
    </button>
  )
}

function TranslationProgressUI({ progress }) {
  // No progress yet — show centred spinner card
  if (!progress) {
    return (
      <div className="mb-6">
        <div className="p-8 bg-violet-50 rounded-xl border border-violet-200 text-center mb-4">
          <Spinner className="w-8 h-8 mx-auto text-violet-500 mb-3" />
          <p className="text-sm text-violet-600 font-medium">正在使用 AI 翻译...</p>
          <p className="text-xs text-violet-400 mt-1">通义千问大模型，翻译准确自然</p>
        </div>
      </div>
    )
  }
  // Streaming progress — show partial markdown
  return (
    <div className="mb-6">
      <div className="flex items-center gap-2 mb-3">
        <Spinner className="w-4 h-4 text-violet-500" />
        <span className="text-xs text-violet-500 font-medium">AI 正在翻译...</span>
      </div>
      <div className="bg-white rounded-xl border border-violet-200 p-5 shadow-sm opacity-80">
        <div className="article-markdown prose prose-gray max-w-none">
          <MarkdownContent content={progress} />
        </div>
      </div>
    </div>
  )
}

/* ── Tiny inline visuals (shared inside this file) ──────────────────────── */

function TranslateIcon({ className }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129" />
    </svg>
  )
}

function Spinner({ className }) {
  return (
    <svg className={`animate-spin ${className}`} fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  )
}

