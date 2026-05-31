/**
 * Chat panel header — title + fullscreen / clear / close buttons.
 */
export default function ChatHeader({ isFullscreen, onToggleFullscreen, onClear, onClose }) {
  return (
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
        <IconButton
          onClick={onToggleFullscreen}
          label={isFullscreen ? '退出全屏' : '全屏观看'}
          className="mr-1"
        >
          {isFullscreen ? (
            <svg className="w-4 h-4 text-gray-400 hover:text-indigo-500 transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 9V4.5M9 9L4.5 4.5M9 9L13.5 4.5M9 9L4.5 13.5M15 15v4.5M15 15L19.5 19.5M15 15L10.5 19.5M15 15L19.5 10.5" />
            </svg>
          ) : (
            <svg className="w-4 h-4 text-gray-400 hover:text-indigo-500 transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 3.75v4.5m0-4.5h4.5m-4.5 0L9 9M3.75 20.25v-4.5m0 4.5h4.5m-4.5 0L9 15M20.25 3.75h-4.5m4.5 0v4.5m0-4.5L15 9m5.25 11.25h-4.5m4.5 0v-4.5m0 4.5L15 15" />
            </svg>
          )}
        </IconButton>
        <IconButton onClick={onClear} label="清空对话" className="mr-1">
          <svg className="w-4 h-4 text-gray-400 hover:text-red-500 transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
          </svg>
        </IconButton>
        <IconButton onClick={onClose} label="关闭对话窗口">
          <svg className="w-5 h-5 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </IconButton>
      </div>
    </div>
  )
}

function IconButton({ onClick, label, className = '', children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      title={label}
      className={`w-8 h-8 rounded-full hover:bg-gray-100 flex items-center justify-center transition-colors ${className}`}
    >
      {children}
    </button>
  )
}
