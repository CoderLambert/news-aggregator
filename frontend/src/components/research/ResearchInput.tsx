import { useEffect, useLayoutEffect, useRef, useState, type ChangeEvent, type KeyboardEvent } from 'react'
import { Send, Square, Database } from 'lucide-react'

const PLACEHOLDERS = [
  '想研究什么话题？',
  '输入问题，我来帮你深挖…',
  '试试「分析 AI 芯片竞争格局」',
  '可以联网搜索哦 🔍',
]

const MAX_HEIGHT = 116

interface ResearchInputProps {
  value: string
  onChange: (value: string) => void
  onSend: () => void
  onCancel?: () => void
  isLoading: boolean
  disabled?: boolean
  loginRequired?: boolean
  localOnly?: boolean
  onToggleLocalOnly?: () => void
}

export default function ResearchInput({
  value,
  onChange,
  onSend,
  onCancel,
  isLoading,
  disabled = false,
  loginRequired = false,
  localOnly = false,
  onToggleLocalOnly,
}: ResearchInputProps) {
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const [placeholder] = useState(() => PLACEHOLDERS[Math.floor(Math.random() * PLACEHOLDERS.length)])

  useEffect(() => {
    if (!isLoading && !disabled) inputRef.current?.focus()
  }, [isLoading, disabled])

  useLayoutEffect(() => {
    const element = inputRef.current
    if (!element) return
    element.style.height = 'auto'
    const nextHeight = Math.min(element.scrollHeight, MAX_HEIGHT)
    element.style.height = `${nextHeight}px`
    element.style.overflowY = element.scrollHeight > MAX_HEIGHT ? 'auto' : 'hidden'
  }, [value])

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      if (canSend) onSend()
    }
  }

  function handleChange(event: ChangeEvent<HTMLTextAreaElement>) {
    onChange(event.target.value)
  }

  const canSend = Boolean(value.trim()) && !isLoading && !disabled

  return (
    <div className={`border-t px-3 pb-3 pt-2 transition-colors duration-200
      ${localOnly
        ? 'border-primary/20 bg-primary/5 backdrop-blur-xl'
        : 'border-border bg-card/90 backdrop-blur-xl'
      }`}
    >
      <div className={`flex items-end gap-2 rounded-2xl p-1.5 transition-all duration-200
        ${localOnly ? 'bg-primary/10' : 'bg-secondary/75'}
        ${canSend ? 'bg-background ring-2 ring-primary/30' : ''}`}
      >
        <textarea
          ref={inputRef}
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder={loginRequired ? '请先登录' : placeholder}
          aria-label="输入研究问题"
          rows={1}
          disabled={disabled}
          className="chat-input-scroll flex-1 bg-transparent border-none resize-none
                     focus:outline-none focus:ring-0
                     text-sm leading-5 text-foreground placeholder:text-muted-foreground
                     py-2 px-3 disabled:opacity-50"
          style={{ minHeight: '36px', maxHeight: `${MAX_HEIGHT}px` }}
        />
        {isLoading ? (
          <button
            type="button"
            onClick={onCancel}
            disabled={!onCancel}
            aria-label="取消研究任务"
            title="请求取消服务端任务；若取消请求失败，任务可能继续运行"
            className="flex-shrink-0 min-h-9 px-2 rounded-xl inline-flex items-center gap-1.5
                       border border-rose-500/25 bg-rose-500/10 text-rose-700 hover:bg-rose-500/20 dark:text-rose-200
                       disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-rose-300"
          >
            <Square className="w-3.5 h-3.5" />
            <span className="text-xs font-medium">取消研究</span>
          </button>
        ) : (
          <button
            type="button"
            onClick={onSend}
            disabled={!canSend}
            aria-label="发送"
            className={`flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center transition-all duration-200
              active:scale-90
              ${canSend
                ? 'bg-primary text-primary-foreground shadow-md shadow-primary/15 hover:scale-105 hover:bg-primary/90 hover:shadow-lg'
                : 'cursor-not-allowed bg-muted text-muted-foreground'
              }`}
          >
            <Send className="w-4 h-4" />
          </button>
        )}
      </div>

      {onToggleLocalOnly && !disabled && (
        <button
          type="button"
          onClick={onToggleLocalOnly}
          disabled={isLoading}
          aria-pressed={localOnly}
          className="mt-2 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full
                     text-[11px] font-medium transition-all duration-150
                     hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring
                     active:scale-95 disabled:opacity-50"
        >
          <Database className={`size-3 transition-colors ${localOnly ? 'text-primary' : 'text-muted-foreground'}`} />
          <span className={`transition-colors ${localOnly ? 'text-primary' : 'text-muted-foreground'}`}>
            {localOnly ? '仅本地新闻库' : '本地+联网搜索'}
          </span>
        </button>
      )}

      <p className="mt-1.5 text-center text-[10px] text-muted-foreground/75">
        {localOnly
          ? '仅搜索本地新闻数据库，不进行联网搜索'
          : '研究助手会调用多个工具深度分析，结果仅供参考'}
      </p>
    </div>
  )
}
