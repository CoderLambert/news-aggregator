import { useRef, useEffect, useState } from 'react'
import { Send, Loader2 } from 'lucide-react'

const PLACEHOLDERS = [
  '想问点什么？',
  '聊聊你的想法…',
  '让我帮你梳理梳理',
  '问我点有趣的吧',
]

export default function ChatInput({ value, onChange, onSend, isLoading, autoFocus }) {
  const inputRef = useRef(null)
  const [placeholder] = useState(
    () => PLACEHOLDERS[Math.floor(Math.random() * PLACEHOLDERS.length)],
  )

  useEffect(() => {
    if (autoFocus) inputRef.current?.focus()
  }, [autoFocus])

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      onSend()
    }
  }

  const canSend = value.trim() && !isLoading

  return (
    <div className="px-3 pt-2 pb-3 bg-white border-t border-neutral-100">
      <div className={`flex items-end gap-2 bg-neutral-100 rounded-2xl p-1.5 transition-all
        ${canSend ? 'ring-2 ring-orange-200' : 'ring-0'}`}
      >
        <textarea
          ref={inputRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          aria-label="输入聊天问题"
          rows="1"
          className="flex-1 bg-transparent border-none resize-none focus:outline-none focus:ring-0
                     text-sm text-neutral-900 placeholder-neutral-400 max-h-24 py-2 px-3"
          style={{ minHeight: '36px' }}
        />
        <button
          type="button"
          onClick={onSend}
          disabled={!canSend}
          aria-label="发送消息"
          className={`flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center transition-all
            active:scale-90
            ${canSend
              ? 'bg-gradient-to-br from-orange-500 to-orange-600 text-white shadow-md hover:shadow-lg hover:scale-105'
              : 'bg-neutral-300 text-neutral-500 cursor-not-allowed'
            }`}
        >
          {isLoading ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Send className="w-4 h-4" />
          )}
        </button>
      </div>
      <p className="text-[10px] text-center text-neutral-400 mt-2">
        小闻偶尔也会犯错，重要信息请以原文为准 🦊
      </p>
    </div>
  )
}
