import { useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronRight, ExternalLink, Globe, RefreshCw } from 'lucide-react'
import type { ChatPhase } from '@/hooks/useChat'
import type { ChatMessage, WebSource } from '@/services/newsWorkflowApi'
import MarkdownContent from '@/components/news-detail/MarkdownContent'
import XiaowenMascot from '@/components/mascot/XiaowenMascot'

const DEFAULT_SUGGESTED_QUESTIONS = [
  '帮我用一句话总结这篇文章',
  '这篇文章里最重要的三个观点是什么？',
  '有什么背景知识可以帮我更好理解？',
]

interface ChatMessageListProps {
  messages: ChatMessage[]
  phase: ChatPhase
  onSuggestionClick?: (text: string) => void
  suggestedQuestions?: string[]
  onRefreshSuggestions?: () => void
  refreshingSuggestions?: boolean
}

export default function ChatMessageList({
  messages,
  phase,
  onSuggestionClick,
  suggestedQuestions,
  onRefreshSuggestions,
  refreshingSuggestions = false,
}: ChatMessageListProps) {
  const endRef = useRef<HTMLDivElement>(null)
  const questions = suggestedQuestions && suggestedQuestions.length > 0 ? suggestedQuestions : DEFAULT_SUGGESTED_QUESTIONS

  useEffect(() => {
    if (typeof endRef.current?.scrollIntoView === 'function') {
      endRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages])

  if (phase === 'loading-history') {
    return <div className="flex h-full items-center justify-center"><XiaowenMascot mood="idle" size={56} /></div>
  }

  if (messages.length === 0) {
    return (
      <div className="animate-message-pop-in flex h-full flex-col items-center justify-center px-4 text-center">
        <div className="animate-mascot-bob"><XiaowenMascot mood="happy" size={88} showShadow /></div>
        <p className="mt-4 text-base font-semibold text-neutral-900">嗨，我是小闻 👋</p>
        <p className="mt-1.5 max-w-[240px] text-xs leading-relaxed text-neutral-500">我已经读完这篇文章了，你想聊点什么？下面是一些建议：</p>
        <div className="mt-5 flex w-full max-w-[280px] flex-col gap-2">
          {questions.map((question) => (
            <button
              key={question}
              type="button"
              onClick={() => onSuggestionClick?.(question)}
              className="rounded-2xl border border-neutral-200 bg-white px-3.5 py-2.5 text-left text-xs text-neutral-700 shadow-sm transition-colors hover:border-orange-300 hover:bg-orange-50 hover:text-orange-900 focus:outline-none focus:ring-2 focus:ring-orange-200"
            >
              {question}
            </button>
          ))}
        </div>
        {onRefreshSuggestions && (
          <button
            type="button"
            onClick={onRefreshSuggestions}
            disabled={refreshingSuggestions}
            aria-label="换一批推荐问题"
            className="mt-3 inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[11px] text-neutral-500 transition-colors hover:bg-orange-50 hover:text-orange-600 focus:outline-none focus:ring-2 focus:ring-orange-200 disabled:cursor-wait disabled:opacity-50"
          >
            <RefreshCw className={`size-3 ${refreshingSuggestions ? 'animate-spin' : ''}`} /><span>换一批</span>
          </button>
        )}
      </div>
    )
  }

  return (
    <>
      {messages.map((message, index) => (
        <div key={message.id ?? `history-${index}`} className={`flex animate-message-pop-in ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
          <div className={`max-w-full break-words rounded-2xl px-4 py-3 text-[15px] leading-relaxed sm:max-w-[85%] ${message.role === 'user' ? 'rounded-tr-md bg-gradient-to-br from-orange-500 to-orange-600 text-white shadow-sm' : 'rounded-tl-md border border-neutral-200 bg-white text-neutral-800 shadow-sm'}`}>
            {message.role === 'assistant' ? (
              message.content ? (
                <div className="prose prose-sm max-w-none"><MarkdownContent content={message.content} /></div>
              ) : (
                <div className="flex flex-col items-start gap-1 py-0.5" role="status" aria-label="小闻正在思考">
                  <div className="flex items-center gap-1.5 px-1"><span className="thinking-dot" /><span className="thinking-dot" /><span className="thinking-dot" /></div>
                  <span className="select-none text-xs text-neutral-400">{message.web_search ? '正在联网搜索…' : '正在思考…'}</span>
                </div>
              )
            ) : <div className="whitespace-pre-wrap">{message.content}</div>}
            {message.role === 'assistant' && message.content && message.web_sources && <WebSources sources={message.web_sources} />}
            {message.role === 'assistant' && message.content && message.web_search && !message.web_sources && (
              <div className="mt-2 flex items-center gap-1 border-t border-neutral-100 pt-2"><Globe className="size-3 text-orange-400" /><span className="text-[10px] text-neutral-400">使用了联网搜索</span></div>
            )}
          </div>
        </div>
      ))}
      <div ref={endRef} />
    </>
  )
}

function WebSources({ sources }: { sources: WebSource[] }) {
  const [expanded, setExpanded] = useState(false)
  if (sources.length === 0) return null
  return (
    <div className="mt-3 border-t border-neutral-100 pt-2">
      <button type="button" onClick={() => setExpanded((current) => !current)} aria-expanded={expanded} className="flex items-center gap-1.5 text-xs text-neutral-500 transition-colors hover:text-orange-600">
        <Globe className="size-3.5 text-orange-400" /><span>搜索来源（{sources.length} 条）</span>
        {expanded ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
      </button>
      {expanded && (
        <div className="mt-2 space-y-2">
          {sources.map((source, index) => (
            <div key={`${source.url ?? source.title}-${index}`} className="rounded-lg border border-neutral-100 bg-neutral-50 p-2 text-xs">
              <a href={source.url || '#'} target="_blank" rel="noopener noreferrer" className="flex items-start gap-1.5 font-medium text-orange-600 hover:text-orange-700">
                <ExternalLink className="mt-0.5 size-3 shrink-0" /><span>{source.title}</span>
              </a>
              {source.snippet && <p className="mt-1 line-clamp-2 leading-relaxed text-neutral-500">{source.snippet}</p>}
              {source.source && <span className="mt-1 inline-block text-[10px] text-neutral-400">{source.source}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
