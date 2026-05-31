import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export default function NewsChatAssistant({ newsId }) {
  const [isOpen, setIsOpen] = useState(false)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const messagesEndRef = useRef(null)
  const inputRef = useRef(null)

  // Load chat history when component mounts or newsId changes
  useEffect(() => {
    setMessages([]) // Clear current chat when switching articles
    setIsLoading(true) // Show loading state
    
    fetch(`/api/news/${newsId}/chat/`)
      .then(res => res.json())
      .then(data => {
        setMessages(data.messages || [])
        setIsLoading(false)
      })
      .catch(err => {
        console.error('Failed to load chat history:', err)
        setIsLoading(false)
      })
  }, [newsId])

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Auto focus input when open
  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus()
    }
  }, [isOpen])

  const handleClearChat = async () => {
    if (window.confirm('确定要清空关于这篇文章的对话记录吗？')) {
      try {
        await fetch(`/api/news/${newsId}/chat/`, { method: 'DELETE' })
        setMessages([])
      } catch (e) {
        console.error('Failed to clear chat:', e)
      }
    }
  }

  const handleSend = async () => {
    if (!input.trim() || isLoading) return

    const userMessage = { role: 'user', content: input.trim() }
    const updatedMessages = [...messages, userMessage]
    
    // Optimistic update
    setMessages(updatedMessages)
    setInput('')
    setIsLoading(true)

    // Add a placeholder for AI response
    const aiMsgId = Date.now()
    setMessages(prev => [...prev, { role: 'assistant', content: '', id: aiMsgId }])

    try {
      const response = await fetch(`/api/news/${newsId}/chat/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: userMessage.content,
          // Backend now handles history persistence, no need to send history array
        }),
      })

      if (!response.ok) {
        throw new Error('Request failed')
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let accumulated = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const chunk = decoder.decode(value, { stream: true })
        accumulated += chunk
        
        // Update the last message (AI placeholder)
        setMessages(prev => {
          const newMsgs = [...prev]
          const lastIdx = newMsgs.length - 1
          newMsgs[lastIdx] = { ...newMsgs[lastIdx], content: accumulated }
          return newMsgs
        })
      }
    } catch (err) {
      console.error('Chat error:', err)
      // Update the last message with error
      setMessages(prev => {
        const newMsgs = [...prev]
        const lastIdx = newMsgs.length - 1
        newMsgs[lastIdx] = { ...newMsgs[lastIdx], content: '抱歉，我遇到了一些问题，请稍后再试。' }
        return newMsgs
      })
    } finally {
      setIsLoading(false)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  if (!isOpen) {
    return (
      <button
        onClick={() => setIsOpen(true)}
        className="fixed bottom-6 right-6 z-50 w-14 h-14 bg-gradient-to-br from-violet-500 to-indigo-600 
                   text-white rounded-full shadow-lg hover:shadow-xl hover:scale-105 active:scale-95 
                   transition-all duration-200 flex items-center justify-center group"
        title="AI 助手"
      >
        <svg className="w-7 h-7 group-hover:rotate-12 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
        </svg>
      </button>
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex flex-col justify-end sm:justify-center sm:items-center pointer-events-none">
      {/* Backdrop */}
      <div 
        className="absolute inset-0 bg-black/20 backdrop-blur-sm pointer-events-auto transition-opacity"
        onClick={() => setIsOpen(false)}
      />

      {/* Chat Window */}
      <div className="relative w-full h-[85vh] sm:h-[600px] sm:w-[450px] bg-white sm:rounded-2xl shadow-2xl 
                      pointer-events-auto flex flex-col overflow-hidden animate-slide-up sm:animate-fade-in">
        
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-100 bg-white/80 backdrop-blur-md">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center shadow-sm">
              <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
              </svg>
            </div>
            <div>
              <h3 className="text-sm font-semibold text-gray-900">AI 新闻助手</h3>
              <p className="text-xs text-gray-500">基于当前文章对话</p>
            </div>
          </div>
          <div className="flex items-center">
            <button 
              onClick={handleClearChat}
              className="w-8 h-8 rounded-full hover:bg-gray-100 flex items-center justify-center transition-colors mr-1"
              title="清空对话"
            >
              <svg className="w-4 h-4 text-gray-400 hover:text-red-500 transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
            <button 
              onClick={() => setIsOpen(false)}
              className="w-8 h-8 rounded-full hover:bg-gray-100 flex items-center justify-center transition-colors"
            >
              <svg className="w-5 h-5 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4 bg-gray-50/50">
          {isLoading && messages.length === 0 ? (
            <div className="flex justify-center items-center h-full">
              <svg className="w-6 h-6 animate-spin text-indigo-500" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            </div>
          ) : (
            <>
              {messages.length === 0 && (
                <div className="flex flex-col items-center justify-center h-full text-center space-y-3 opacity-60">
                  <svg className="w-12 h-12 text-indigo-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
                  </svg>
                  <div className="space-y-1">
                    <p className="text-sm font-medium text-gray-600">嗨！我是你的 AI 助手</p>
                    <p className="text-xs text-gray-500 max-w-[200px]">你可以问我关于这篇文章的任何问题，比如摘要、观点分析等。</p>
                  </div>
                </div>
              )}

              {messages.map((msg, i) => (
                <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[85%] px-4 py-3 text-[15px] leading-relaxed whitespace-pre-wrap break-words
                    ${msg.role === 'user' 
                      ? 'bg-indigo-600 text-white rounded-2xl rounded-tr-sm' 
                      : 'bg-white border border-gray-200 text-gray-800 rounded-2xl rounded-tl-sm shadow-sm'
                    }`}>
                    {msg.role === 'assistant' ? (
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {msg.content || '...'}
                      </ReactMarkdown>
                    ) : (
                      msg.content
                    )}
                  </div>
                </div>
              ))}
              <div ref={messagesEndRef} />
            </>
          )}
        </div>

        {/* Input Area */}
        <div className="p-3 bg-white border-t border-gray-100">
          <div className="flex items-end gap-2 bg-gray-100 rounded-2xl p-1.5">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="输入你的问题..."
              className="flex-1 bg-transparent border-none resize-none focus:ring-0 text-sm text-gray-900 placeholder-gray-400 max-h-24 py-2 px-3"
              rows="1"
              style={{ minHeight: '36px' }}
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || isLoading}
              className={`w-9 h-9 rounded-xl flex items-center justify-center transition-all
                ${input.trim() && !isLoading 
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
      </div>
    </div>
  )
}
