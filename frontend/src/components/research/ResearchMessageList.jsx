import { useRef, useEffect } from 'react'
import { Search, Sparkles } from 'lucide-react'
import MarkdownContent from '../news-detail/MarkdownContent'
import ProcessTimeline from './ProcessTimeline'

const SUGGESTED_QUERIES = [
  '最近 LLM Agent 有什么新进展？',
  '分析 AI 芯片竞争格局',
  'React 和 Vue 哪个更受欢迎？',
]

/**
 * Renders research messages with a clean, modern design.
 * Tool calls render as a vertical ProcessTimeline.
 * Search results render as clickable article cards.
 */
export default function ResearchMessageList({
  messages,
  phase,
  searchResults,
  onSuggestionClick,
}) {
  const endRef = useRef(null)

  useEffect(() => {
    if (typeof endRef.current?.scrollIntoView === 'function') {
      endRef.current.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  }, [messages])

  if (messages.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center px-6 animate-message-pop-in">
        {/* Animated search icon with gradient ring */}
        <div className="relative mb-5">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-violet-100 to-orange-50 flex items-center justify-center shadow-lg shadow-violet-100/50">
            <Search className="w-7 h-7 text-violet-500" />
          </div>
          <div className="absolute -top-1 -right-1 w-5 h-5 rounded-full bg-gradient-to-br from-orange-400 to-pink-400 flex items-center justify-center shadow-sm">
            <Sparkles className="w-3 h-3 text-white" />
          </div>
        </div>

        <p className="text-lg font-bold text-neutral-900">新闻研究助手</p>
        <p className="mt-1.5 text-xs text-neutral-400 max-w-[280px] leading-relaxed">
          深度分析新闻库内容、联网搜索补充信息、追踪话题趋势
        </p>

        {/* Suggested queries — 3 column grid */}
        <div className="mt-6 grid grid-cols-1 gap-2 w-full max-w-[340px]">
          {SUGGESTED_QUERIES.map(q => (
            <button
              key={q}
              type="button"
              onClick={() => onSuggestionClick?.(q)}
              className="text-left px-4 py-3 rounded-xl bg-white border border-neutral-100
                         text-sm text-neutral-700 hover:border-violet-200 hover:bg-violet-50/50
                         hover:text-violet-800 transition-all duration-150 shadow-sm
                         hover:shadow-md active:scale-[0.98]
                         focus:outline-none focus:ring-2 focus:ring-violet-200"
            >
              {q}
            </button>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {messages.map((msg, i) => (
        <div
          key={i}
          className={`flex animate-message-pop-in ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
        >
          {msg.role === 'user' ? (
            <div className="max-w-[85%] px-4 py-2.5 text-[14px] leading-relaxed break-words
              bg-gradient-to-br from-violet-500 to-violet-600 text-white
              rounded-2xl rounded-tr-md shadow-sm shadow-violet-200/50">
              <div className="whitespace-pre-wrap">{msg.content}</div>
            </div>
          ) : (
            <div className="max-w-full w-full">
              {/* Tool calls as vertical timeline */}
              {msg.toolCalls && msg.toolCalls.length > 0 && (
                <div className="mb-3">
                  <ProcessTimeline toolCalls={msg.toolCalls} searchResults={searchResults} />
                </div>
              )}
              {/* Final answer */}
              {msg.content ? (
                <div className="prose prose-sm max-w-none">
                  <MarkdownContent content={msg.content} />
                </div>
              ) : (phase === 'thinking' || phase === 'tool_calling') && (!msg.toolCalls || msg.toolCalls.every(tc => tc.status !== 'running')) ? (
                <div className="flex items-center gap-2 py-2">
                  <div className="w-2 h-2 rounded-full bg-violet-400 animate-pulse" />
                  <div className="w-2 h-2 rounded-full bg-violet-400 animate-pulse [animation-delay:150ms]" />
                  <div className="w-2 h-2 rounded-full bg-violet-400 animate-pulse [animation-delay:300ms]" />
                  <span className="text-xs text-neutral-400 ml-1">
                    {phase === 'thinking' ? '思考中…' : '处理中…'}
                  </span>
                </div>
              ) : null}
            </div>
          )}
        </div>
      ))}
      <div ref={endRef} />
    </div>
  )
}
