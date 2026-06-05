import { useRef, useEffect, useState, useLayoutEffect } from 'react'
import { Send, Loader2, Database } from 'lucide-react'

const PLACEHOLDERS = [
  '想研究什么话题？',
  '输入问题，我来帮你深挖…',
  '试试「分析 AI 芯片竞争格局」',
  '可以联网搜索哦 🔍',
]

const MAX_HEIGHT = 116

export default function ResearchInput({ value, onChange, onSend, isLoading, disabled = false, localOnly = false, onToggleLocalOnly }) {
  const inputRef = useRef(null)
  const [placeholder] = useState(
    () => disabled
      ? '请先登录'
      : PLACEHOLDERS[Math.floor(Math.random() * PLACEHOLDERS.length)],
  )

  useEffect(() => {
    if (!isLoading && !disabled) inputRef.current?.focus()
  }, [isLoading, disabled])

  useLayoutEffect(() => {
    const el = inputRef.current
    if (!el) return
    el.style.height = 'auto'
    const next = Math.min(el.scrollHeight, MAX_HEIGHT)
    el.style.height = `${next}px`
    el.style.overflowY = el.scrollHeight > MAX_HEIGHT ? 'auto' : 'hidden'
  }, [value])

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      onSend()
    }
  }

  const canSend = value.trim() && !isLoading && !disabled

  return (
    <div className="px-3 pt-2 pb-3 bg-white/60 backdrop-blur-xl border-t border-neutral-100/50">
      <div className={`flex items-end gap-2 bg-neutral-50 rounded-2xl p-1.5 transition-all duration-200
        ${canSend ? 'ring-2 ring-violet-300/50 bg-white' : ''}`}
      >
        <textarea
          ref={inputRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          aria-label="输入研究问题"
          rows="1"
          disabled={disabled}
          className="chat-input-scroll flex-1 bg-transparent border-none resize-none
                     focus:outline-none focus:ring-0
                     text-sm leading-5 text-neutral-900 placeholder-neutral-400
                     py-2 px-3 disabled:opacity-50"
          style={{ minHeight: '36px', maxHeight: `${MAX_HEIGHT}px` }}
        />
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
          {isLoading ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Send className="w-4 h-4" />
          )}
        </button>
      </div>

      {/* Local-only toggle */}
      {onToggleLocalOnly && !disabled && (
        <button
          type="button"
          onClick={onToggleLocalOnly}
          className="mt-2 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full
                     text-[11px] font-medium transition-all duration-150
                     focus:outline-none focus:ring-2 focus:ring-violet-200
                     active:scale-95"
        >
          <Database className={`w-3 h-3 transition-colors ${localOnly ? 'text-violet-500' : 'text-neutral-300'}`} />
          <span className={`transition-colors ${localOnly ? 'text-violet-600' : 'text-neutral-400'}`}>
            {localOnly ? '仅本地新闻库' : '本地+联网搜索'}
          </span>
        </button>
      )}

      {/* Footer hint */}
      <p className="text-[10px] text-center text-neutral-300 mt-1.5">
        {localOnly
          ? '仅搜索本地新闻数据库，不进行联网搜索'
          : '研究助手会调用多个工具深度分析，结果仅供参考'}
      </p>
    </div>
  )
}
