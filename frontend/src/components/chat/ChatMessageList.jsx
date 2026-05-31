import { useRef, useEffect } from 'react'
import NodeRenderer from 'markstream-react'

const CODE_BLOCK_PROPS = { showHeader: true, showCopyButton: true, showCollapseButton: false }
const CODE_BLOCK_THEMES = {
  themes: ['vitesse-light'],
  darkTheme: 'vitesse-light',
  lightTheme: 'vitesse-light',
  monacoOptions: { fontSize: 13, wordWrap: 'on', minimap: { enabled: false } },
}

export default function ChatMessageList({ messages, isLoading }) {
  const endRef = useRef(null)

  // Auto-scroll on new content
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  if (isLoading && messages.length === 0) {
    return (
      <div className="flex justify-center items-center h-full">
        <svg className="w-6 h-6 animate-spin text-indigo-500" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      </div>
    )
  }

  if (messages.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center space-y-3 opacity-60">
        <svg className="w-12 h-12 text-indigo-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
        </svg>
        <div className="space-y-1">
          <p className="text-sm font-medium text-gray-600">嗨！我是你的 AI 助手</p>
          <p className="text-xs text-gray-500 max-w-[200px]">你可以问我关于这篇文章的任何问题，比如摘要、观点分析等。</p>
        </div>
      </div>
    )
  }

  return (
    <>
      {messages.map((msg, i) => (
        <div key={msg.id ?? i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
          <div className={`max-w-full sm:max-w-[85%] px-4 py-3 text-[15px] leading-relaxed break-words
            ${msg.role === 'user'
              ? 'bg-indigo-600 text-white rounded-2xl rounded-tr-sm'
              : 'bg-white border border-gray-200 text-gray-800 rounded-2xl rounded-tl-sm shadow-sm'
            }`}>
            {msg.role === 'assistant' ? (
              <div className="prose prose-sm max-w-none">
                <NodeRenderer content={msg.content || '...'} codeBlockProps={CODE_BLOCK_PROPS} codeBlockThemes={CODE_BLOCK_THEMES} />
              </div>
            ) : (
              <div className="whitespace-pre-wrap">{msg.content}</div>
            )}
          </div>
        </div>
      ))}
      <div ref={endRef} />
    </>
  )
}
