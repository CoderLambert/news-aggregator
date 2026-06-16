import { useRef, useEffect, useState } from 'react'
import { RefreshCw, Globe, ChevronDown, ChevronRight, ExternalLink } from 'lucide-react'
import MarkdownContent from '../news-detail/MarkdownContent'
import XiaowenMascot from '../mascot/XiaowenMascot'

const DEFAULT_SUGGESTED_QUESTIONS = [
  '帮我用一句话总结这篇文章',
  '这篇文章里最重要的三个观点是什么？',
  '有什么背景知识可以帮我更好理解？',
]

/**
 * Renders chat messages, the empty state with suggested questions,
 * and the "thinking" placeholder while waiting for the first token.
 *
 * Props:
 *   - messages: chat history
 *   - phase:    from useChat phase machine — drives the thinking dots
 *   - onSuggestionClick(text): user picks a suggested question
 *   - suggestedQuestions: optional override; falls back to the hardcoded 3
 *   - onRefreshSuggestions: optional — when provided, shows the "换一批"
 *       button in the empty state. Called when user clicks it.
 *   - refreshingSuggestions: when true, button disabled + icon spins
 */
export default function ChatMessageList({
  messages,
  phase,
  onSuggestionClick,
  suggestedQuestions,
  onRefreshSuggestions,
  refreshingSuggestions = false,
}) {
  const endRef = useRef(null)
  const questions =
    suggestedQuestions && suggestedQuestions.length >= 1
      ? suggestedQuestions
      : DEFAULT_SUGGESTED_QUESTIONS

  // Auto-scroll on new content. jsdom lacks scrollIntoView, so guard.
  useEffect(() => {
    if (typeof endRef.current?.scrollIntoView === 'function') {
      endRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages])

  if (phase === 'loading-history') {
    return (
      <div className="flex justify-center items-center h-full">
        <XiaowenMascot mood="idle" size={56} />
      </div>
    )
  }

  if (messages.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center px-4 animate-message-pop-in">
        <div className="animate-mascot-bob">
          <XiaowenMascot mood="happy" size={88} showShadow />
        </div>
        <p className="mt-4 text-base font-semibold text-neutral-900">嗨，我是小闻 👋</p>
        <p className="mt-1.5 text-xs text-neutral-500 max-w-[240px] leading-relaxed">
          我已经读完这篇文章了，你想聊点什么？下面是一些建议：
        </p>
        <div className="mt-5 flex flex-col gap-2 w-full max-w-[280px]">
          {questions.map(q => (
            <button
              key={q}
              type="button"
              onClick={() => onSuggestionClick?.(q)}
              className="text-left px-3.5 py-2.5 rounded-2xl bg-white border border-neutral-200
                         text-xs text-neutral-700 hover:border-orange-300 hover:bg-orange-50
                         hover:text-orange-900 transition-colors shadow-sm
                         focus:outline-none focus:ring-2 focus:ring-orange-200"
            >
              {q}
            </button>
          ))}
        </div>
        {onRefreshSuggestions && (
          <button
            type="button"
            onClick={onRefreshSuggestions}
            disabled={refreshingSuggestions}
            aria-label="换一批推荐问题"
            className="mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full
                       text-[11px] text-neutral-500 hover:text-orange-600
                       hover:bg-orange-50 transition-colors
                       disabled:opacity-50 disabled:cursor-wait
                       focus:outline-none focus:ring-2 focus:ring-orange-200"
          >
            <RefreshCw
              className={`w-3 h-3 ${refreshingSuggestions ? 'animate-spin' : ''}`}
            />
            <span>换一批</span>
          </button>
        )}
      </div>
    )
  }

  return (
    <>
      {messages.map((msg, i) => (
        <div
          key={msg.id ?? i}
          className={`flex animate-message-pop-in ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
        >
          <div className={`max-w-full sm:max-w-[85%] px-4 py-3 text-[15px] leading-relaxed break-words
            ${msg.role === 'user'
              ? 'bg-gradient-to-br from-orange-500 to-orange-600 text-white rounded-2xl rounded-tr-md shadow-sm'
              : 'bg-white border border-neutral-200 text-neutral-800 rounded-2xl rounded-tl-md shadow-sm'
            }`}>
            {msg.role === 'assistant' ? (
              msg.content ? (
                <div className="prose prose-sm max-w-none">
                  <MarkdownContent content={msg.content} />
                </div>
              ) : (
                // Empty assistant message: show thinking indicator immediately
                // so the user sees their message was received while waiting for
                // the first token from the backend.
                <div className="flex flex-col items-start gap-1 py-0.5">
                  <div className="flex items-center gap-1.5 px-1">
                    <span className="thinking-dot" />
                    <span className="thinking-dot" />
                    <span className="thinking-dot" />
                  </div>
                  <span className="text-xs text-neutral-400 select-none">
                    {msg.web_search ? '正在联网搜索…' : '正在思考…'}
                  </span>
                </div>
              )
            ) : (
              <div className="whitespace-pre-wrap">{msg.content}</div>
            )}
            {msg.role === 'assistant' && msg.content && msg.web_sources && (
              <WebSources sources={msg.web_sources} />
            )}
            {msg.role === 'assistant' && msg.content && msg.web_search && !msg.web_sources && (
              <div className="mt-2 pt-2 border-t border-neutral-100 flex items-center gap-1">
                <Globe className="w-3 h-3 text-orange-400" />
                <span className="text-[10px] text-neutral-400">使用了联网搜索</span>
              </div>
            )}
          </div>
        </div>
      ))}
      <div ref={endRef} />
    </>
  )
}

/**
 * Collapsible web search sources panel displayed below assistant messages.
 */
function WebSources({ sources }) {
  const [expanded, setExpanded] = useState(false)

  if (!sources || sources.length === 0) return null

  return (
    <div className="mt-3 pt-2 border-t border-neutral-100">
      <button
        type="button"
        onClick={() => setExpanded(prev => !prev)}
        className="flex items-center gap-1.5 text-xs text-neutral-500 hover:text-orange-600 transition-colors select-none cursor-pointer"
      >
        <Globe className="w-3.5 h-3.5 text-orange-400" />
        <span>搜索来源 ({sources.length} 条)</span>
        {expanded
          ? <ChevronDown className="w-3 h-3" />
          : <ChevronRight className="w-3 h-3" />
        }
      </button>

      {expanded && (
        <div className="mt-2 space-y-2">
          {sources.map((s, i) => (
            <div
              key={i}
              className="p-2 rounded-lg bg-neutral-50 border border-neutral-100 text-xs"
            >
              <a
                href={s.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-start gap-1.5 text-orange-600 hover:text-orange-700 font-medium"
              >
                <ExternalLink className="w-3 h-3 mt-0.5 flex-shrink-0" />
                <span>{s.title}</span>
              </a>
              {s.snippet && (
                <p className="mt-1 text-neutral-500 leading-relaxed line-clamp-2">
                  {s.snippet}
                </p>
              )}
              <span className="mt-1 inline-block text-[10px] text-neutral-400">
                {s.source}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
