import { useRef, useEffect } from 'react'

export default function ChatInput({ value, onChange, onSend, isLoading, autoFocus }) {
  const inputRef = useRef(null)

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
    <div className="p-3 bg-white border-t border-gray-100">
      <div className="flex items-end gap-2 bg-gray-100 rounded-2xl p-1.5">
        <textarea
          ref={inputRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入你的问题..."
          aria-label="输入聊天问题"
          rows="1"
          className="flex-1 bg-transparent border-none resize-none focus:ring-0 text-sm text-gray-900 placeholder-gray-400 max-h-24 py-2 px-3"
          style={{ minHeight: '36px' }}
        />
        <button
          type="button"
          onClick={onSend}
          disabled={!canSend}
          aria-label="发送消息"
          className={`w-9 h-9 rounded-xl flex items-center justify-center transition-all
            ${canSend
              ? 'bg-indigo-600 text-white hover:bg-indigo-700 shadow-md'
              : 'bg-gray-300 text-gray-500 cursor-not-allowed'
            }`}
        >
          {isLoading ? (
            <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          ) : (
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
            </svg>
          )}
        </button>
      </div>
      <p className="text-[10px] text-center text-gray-400 mt-2">AI 生成内容仅供参考，请以原文为准。</p>
    </div>
  )
}
