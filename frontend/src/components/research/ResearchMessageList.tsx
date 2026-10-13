import { useEffect, useRef } from 'react'
import { Search, Sparkles } from 'lucide-react'
import MarkdownContent from '@/components/news-detail/MarkdownContent'
import ProcessTimeline from './ProcessTimeline'
import type { ResearchMessage, ResearchPhase, ResearchSearchResult } from '@/types/research'

const SUGGESTED_QUERIES = [
  '最近 LLM Agent 有什么新进展？',
  '分析 AI 芯片竞争格局',
  'React 和 Vue 哪个更受欢迎？',
]

interface ResearchMessageListProps {
  messages: ResearchMessage[]
  phase: ResearchPhase
  searchResults: ResearchSearchResult[]
  onSuggestionClick?: (query: string) => void
  disabled?: boolean
}

export default function ResearchMessageList({ messages, phase, searchResults, onSuggestionClick, disabled = false }: ResearchMessageListProps) {
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (typeof endRef.current?.scrollIntoView === 'function') {
      endRef.current.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  }, [messages])

  if (messages.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center px-6 animate-message-pop-in">
        <div className="relative mb-5">
          <div className="flex size-16 items-center justify-center rounded-2xl bg-primary/10 shadow-lg shadow-primary/10">
            <Search className="size-7 text-primary" />
          </div>
          <div className="absolute -top-1 -right-1 w-5 h-5 rounded-full bg-gradient-to-br from-orange-400 to-pink-400 flex items-center justify-center shadow-sm">
            <Sparkles className="w-3 h-3 text-white" />
          </div>
        </div>

        <p className="text-lg font-bold text-foreground">新闻研究助手</p>
        <p className="mt-1.5 max-w-[280px] text-xs leading-relaxed text-muted-foreground">
          深度分析新闻库内容、联网搜索补充信息、追踪话题趋势
        </p>

        <div className="mt-6 grid grid-cols-1 gap-2 w-full max-w-[340px]">
          {SUGGESTED_QUERIES.map((query) => (
            <button
              key={query}
              type="button"
              onClick={() => onSuggestionClick?.(query)}
              disabled={disabled}
              className="rounded-xl border border-border bg-card px-4 py-3 text-left text-sm text-foreground
                         shadow-sm transition-all duration-150 hover:-translate-y-0.5 hover:border-primary/35
                         hover:bg-accent hover:text-primary hover:shadow-md active:scale-[0.98]
                         focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {query}
            </button>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {messages.map((message) => {
        const medicalSources = (message.toolCalls ?? []).flatMap(call => [
          ...call.articles.filter(article => article.is_medical && article.url).map(article => ({ title: article.title ?? '原文来源', url: article.url! })),
          ...(call.articleIsMedical && call.articleUrl ? [{ title: call.articleTitle || '原文来源', url: call.articleUrl }] : []),
        ])
        const sources = [...new Map(medicalSources.map(source => [source.url, source])).values()]
        return (
        <div
          key={message.id}
          className={`flex animate-message-pop-in ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
        >
          {message.role === 'user' ? (
            <div className="max-w-[85%] px-4 py-2.5 text-[14px] leading-relaxed break-words
              rounded-2xl rounded-tr-md bg-primary text-primary-foreground shadow-sm shadow-primary/15">
              <div className="whitespace-pre-wrap">{message.content}</div>
            </div>
          ) : (
            <div className="max-w-full w-full">
              {message.toolCalls && message.toolCalls.length > 0 && (
                <div className="mb-3">
                  <ProcessTimeline toolCalls={message.toolCalls} searchResults={searchResults} />
                </div>
              )}
              {message.content ? (
                <div className="prose prose-sm max-w-none">
                  <MarkdownContent content={message.content} />
                </div>
              ) : (phase === 'thinking' || phase === 'tool_calling') && (!message.toolCalls || message.toolCalls.every((call) => call.status !== 'running')) ? (
                <div className="flex items-center gap-2 py-2" role="status" aria-label={phase === 'thinking' ? '思考中' : '处理中'}>
                  <div className="w-2 h-2 rounded-full bg-violet-400 animate-pulse" />
                  <div className="w-2 h-2 rounded-full bg-violet-400 animate-pulse [animation-delay:150ms]" />
                  <div className="w-2 h-2 rounded-full bg-violet-400 animate-pulse [animation-delay:300ms]" />
                  <span className="ml-1 text-xs text-muted-foreground">{phase === 'thinking' ? '思考中…' : '处理中…'}</span>
                </div>
              ) : null}
              {message.content && sources.length > 0 && <div className="mt-3 rounded-lg border border-border p-3 text-xs text-muted-foreground">
                <p>新闻资讯，不构成医疗建议。</p>
                <ul className="mt-2 space-y-1">{sources.map(source => <li key={source.url}><a className="text-primary underline" href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a></li>)}</ul>
              </div>}
            </div>
          )}
        </div>
      )})}
      <div ref={endRef} />
    </div>
  )
}
