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
  localOnly = false,
  onToggleLocalOnly,
}: ResearchInputProps) {
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const [placeholder] = useState(() => disabled
    ? '请先登录'
    : PLACEHOLDERS[Math.floor(Math.random() * PLACEHOLDERS.length)])

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
    <div className={`px-3 pt-2 pb-3 border-t transition-colors duration-200
      ${localOnly
        ? 'bg-violet-50/60 backdrop-blur-xl border-violet-100/50'
        : 'bg-white/60 backdrop-blur-xl border-neutral-100/50'
      }`}
    >
      <div className={`flex items-end gap-2 rounded-2xl p-1.5 transition-all duration-200
        ${localOnly ? 'bg-violet-100/50' : 'bg-neutral-50'}
        ${canSend ? (localOnly ? 'ring-2 ring-violet-400/60 bg-white' : 'ring-2 ring-violet-300/50 bg-white') : ''}`}
      >
        <textarea
          ref={inputRef}
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          aria-label="输入研究问题"
          rows={1}
          disabled={disabled}
          className="chat-input-scroll flex-1 bg-transparent border-none resize-none
                     focus:outline-none focus:ring-0
                     text-sm leading-5 text-neutral-900 placeholder-neutral-400
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
                       bg-rose-50 text-rose-700 border border-rose-100 hover:bg-rose-100
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
                ? 'bg-gradient-to-br from-violet-500 to-violet-600 text-white shadow-md shadow-violet-200/50 hover:shadow-lg hover:shadow-violet-300/50 hover:scale-105'
                : 'bg-neutral-200 text-neutral-400 cursor-not-allowed'
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
                     focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-200
                     active:scale-95 disabled:opacity-50"
        >
          <Database className={`w-3 h-3 transition-colors ${localOnly ? 'text-violet-500' : 'text-neutral-300'}`} />
          <span className={`transition-colors ${localOnly ? 'text-violet-600' : 'text-neutral-400'}`}>
            {localOnly ? '仅本地新闻库' : '本地+联网搜索'}
          </span>
        </button>
      )}

      <p className="text-[10px] text-center text-neutral-300 mt-1.5">
        {localOnly
          ? '仅搜索本地新闻数据库，不进行联网搜索'
          : '研究助手会调用多个工具深度分析，结果仅供参考'}
      </p>
    </div>
  )
}
