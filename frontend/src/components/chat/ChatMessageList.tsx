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
  medicalSourceUrl?: string
  messages: ChatMessage[]
  phase: ChatPhase
  onSuggestionClick?: (text: string) => void
  suggestedQuestions?: string[]
  suggestionContextScope?: 'full' | 'summary' | 'excerpt'
  suggestionsGenerated?: boolean
  onRefreshSuggestions?: () => void
  refreshingSuggestions?: boolean
}

export default function ChatMessageList({
  medicalSourceUrl,
  messages,
  phase,
  onSuggestionClick,
  suggestedQuestions,
  suggestionContextScope,
  suggestionsGenerated,
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
      <div className="animate-message-pop-in mx-auto flex min-h-full w-full max-w-4xl flex-col items-center px-2 pb-8 pt-8 text-center sm:px-4 sm:pt-12">
        <div className="animate-mascot-bob"><XiaowenMascot mood="happy" size={72} showShadow /></div>
        <p className="mt-3 text-base font-semibold text-foreground">嗨，我是小闻 👋</p>
        <p className="mt-1.5 max-w-lg text-sm leading-relaxed text-muted-foreground">我会根据当前可用的文章内容回答。选择一个问题，或者直接在下方输入。</p>
        {suggestionContextScope === 'excerpt' && <p className="mt-2 text-xs text-muted-foreground">推荐问题仅根据文章节选生成，可能未覆盖全文。</p>}
        {suggestionContextScope === 'summary' && <p className="mt-2 text-xs text-muted-foreground">推荐问题依据当前可用摘要生成。</p>}
        {suggestionsGenerated === false && <p className="mt-2 text-xs text-muted-foreground">当前为通用建议；AI 个性化推荐需要配置个人模型额度。</p>}
        <div className="mt-5 grid w-full max-w-3xl grid-cols-1 gap-2 sm:grid-cols-2">
          {questions.map((question) => (
            <button
              key={question}
              type="button"
              onClick={() => onSuggestionClick?.(question)}
              className="rounded-xl border border-border bg-card px-4 py-3 text-left text-sm leading-relaxed text-foreground transition-colors hover:border-primary/35 hover:bg-primary/6 focus:outline-none focus:ring-2 focus:ring-primary/25"
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
            className="mt-3 inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[11px] text-muted-foreground transition-colors hover:bg-accent hover:text-primary focus:outline-none focus:ring-2 focus:ring-primary/25 disabled:cursor-wait disabled:opacity-50"
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
        <div key={message.id ?? `history-${index}`} className={`mx-auto flex w-full max-w-5xl animate-message-pop-in ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
          <div className={`max-w-full break-words rounded-2xl px-4 py-2.5 text-[15px] leading-relaxed sm:max-w-[85%] ${message.role === 'user' ? 'rounded-tr-md bg-primary text-primary-foreground shadow-sm' : 'rounded-tl-md border border-border bg-card text-card-foreground shadow-sm'}`}>
            {message.role === 'assistant' && (message.context_scope === 'summary' || message.context_scope === 'excerpt') && (
              <p className="mb-2 text-xs text-muted-foreground">{message.context_scope === 'summary' ? '当前回答基于摘要' : '当前回答基于文章节选'}</p>
            )}
            {message.role === 'assistant' ? (
              message.content ? (
                <div className="chat-message-markdown"><MarkdownContent content={message.content} /></div>
              ) : (
                <div className="flex flex-col items-start gap-1 py-0.5" role="status" aria-label="小闻正在思考">
                  <div className="flex items-center gap-1.5 px-1"><span className="thinking-dot" /><span className="thinking-dot" /><span className="thinking-dot" /></div>
                  <span className="select-none text-xs text-muted-foreground">{message.web_search ? '正在联网搜索…' : '正在思考…'}</span>
                </div>
              )
            ) : <div className="whitespace-pre-wrap">{message.content}</div>}
            {message.role === 'assistant' && message.content && medicalSourceUrl && <p className="mt-3 border-t border-border pt-2 text-xs text-muted-foreground">新闻资讯，不构成医疗建议。 <a className="text-primary underline" href={medicalSourceUrl} target="_blank" rel="noopener noreferrer">原文来源</a></p>}
            {message.role === 'assistant' && message.content && message.web_sources && <WebSources sources={message.web_sources} />}
            {message.role === 'assistant' && message.content && message.web_search && !message.web_sources && (
              <div className="mt-2 flex items-center gap-1 border-t border-border pt-2"><Globe className="size-3 text-primary" /><span className="text-[10px] text-muted-foreground">使用了联网搜索</span></div>
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
    <div className="mt-3 border-t border-border pt-2">
      <button type="button" onClick={() => setExpanded((current) => !current)} aria-expanded={expanded} className="flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-primary">
        <Globe className="size-3.5 text-primary" /><span>搜索来源（{sources.length} 条）</span>
        {expanded ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
      </button>
      {expanded && (
        <div className="mt-2 space-y-2">
          {sources.map((source, index) => (
            <div key={`${source.url ?? source.title}-${index}`} className="rounded-lg border border-border bg-secondary/50 p-2 text-xs">
              <a href={source.url || '#'} target="_blank" rel="noopener noreferrer" className="flex items-start gap-1.5 font-medium text-primary hover:underline">
                <ExternalLink className="mt-0.5 size-3 shrink-0" /><span>{source.title}</span>
              </a>
              {source.snippet && <p className="mt-1 line-clamp-2 leading-relaxed text-muted-foreground">{source.snippet}</p>}
              {source.source && <span className="mt-1 inline-block text-[10px] text-muted-foreground">{source.source}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
