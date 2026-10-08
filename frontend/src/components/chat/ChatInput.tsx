import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { ChangeEvent, KeyboardEvent } from 'react'
import { Globe, Loader2, Send, Square } from 'lucide-react'
import { Button } from '@/components/ui/button'

const PLACEHOLDERS = ['想问点什么？', '聊聊你的想法…', '让我帮你梳理梳理', '问我点有趣的吧']
const MAX_HEIGHT = 116

interface ChatInputProps {
  value: string
  onChange: (value: string) => void
  onSend: () => void
  onStop?: () => void
  isLoading: boolean
  autoFocus?: boolean
  webSearch?: boolean
  onWebSearchToggle?: () => void
}

export default function ChatInput({
  value,
  onChange,
  onSend,
  onStop,
  isLoading,
  autoFocus,
  webSearch = false,
  onWebSearchToggle,
}: ChatInputProps) {
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const [placeholder] = useState(() => PLACEHOLDERS[Math.floor(Math.random() * PLACEHOLDERS.length)])

  useEffect(() => {
    if (autoFocus) inputRef.current?.focus()
  }, [autoFocus])

  useLayoutEffect(() => {
    const element = inputRef.current
    if (!element) return
    element.style.height = 'auto'
    const nextHeight = Math.min(element.scrollHeight, MAX_HEIGHT)
    element.style.height = `${nextHeight}px`
    element.style.overflowY = element.scrollHeight > MAX_HEIGHT ? 'auto' : 'hidden'
  }, [value])

  function handleChange(event: ChangeEvent<HTMLTextAreaElement>) {
    onChange(event.currentTarget.value)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey && !isLoading) {
      event.preventDefault()
      onSend()
    }
  }

  const canSend = Boolean(value.trim()) && !isLoading
  return (
    <div className="border-t border-neutral-100 bg-white px-3 pb-3 pt-2">
      <div className={`flex items-end gap-2 rounded-2xl bg-neutral-100 p-1.5 transition-all ${canSend ? 'ring-2 ring-orange-200' : 'ring-0'}`}>
        <textarea
          ref={inputRef}
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          aria-label="输入聊天问题"
          rows={1}
          className="chat-input-scroll flex-1 resize-none border-none bg-transparent px-3 py-2 text-sm leading-5 text-neutral-900 placeholder-neutral-400 focus:outline-none focus:ring-0"
          style={{ minHeight: '36px', maxHeight: `${MAX_HEIGHT}px` }}
        />
        {onWebSearchToggle && (
          <Button
            type="button"
            onClick={onWebSearchToggle}
            aria-pressed={webSearch}
            aria-label={webSearch ? '关闭联网搜索' : '开启联网搜索'}
            title={webSearch ? '已开启联网搜索' : '开启联网搜索'}
            variant={webSearch ? 'secondary' : 'ghost'}
            size="sm"
            className={`shrink-0 px-2 text-[11px] ${webSearch ? 'bg-orange-100 text-orange-700 ring-1 ring-orange-300' : 'text-neutral-500'}`}
          >
            <Globe className="mr-0.5 size-3.5" />联网
          </Button>
        )}
        {isLoading && onStop ? (
          <Button type="button" onClick={onStop} aria-label="停止接收回复" title="停止接收回复" variant="outline" size="icon" className="size-9 shrink-0 rounded-xl">
            <Square className="size-3.5 fill-current" />
          </Button>
        ) : (
          <Button type="button" onClick={onSend} disabled={!canSend} aria-label="发送消息" size="icon" className="size-9 shrink-0 rounded-xl">
            {isLoading ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />}
          </Button>
        )}
      </div>
      <p className="mt-2 text-center text-[10px] text-neutral-400">小闻偶尔也会犯错，重要信息请以原文为准 🦊</p>
      {isLoading && <p className="sr-only">停止接收只会关闭本页连接，服务器可能仍会处理本次请求。</p>}
    </div>
  )
}
