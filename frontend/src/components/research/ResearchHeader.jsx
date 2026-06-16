import { Minimize2, Maximize2, Plus, X, ChevronDown, History } from 'lucide-react'
import { Button } from '../ui/button'
import { useState, useRef, useEffect } from 'react'
import { Search } from 'lucide-react'
import { createPortal } from 'react-dom'

/**
 * Research panel header — clean, minimal design.
 * Session switcher dropdown uses a portal to escape overflow-hidden clipping.
 */
export default function ResearchHeader({
  title = '新闻研究',
  phase,
  isFullscreen,
  onToggleFullscreen,
  onNewSession,
  onClose,
  sessions = [],
  activeSessionId,
  onSelectSession,
}) {
  const [showSessionMenu, setShowSessionMenu] = useState(false)
  const btnRef = useRef(null)
  const menuRef = useRef(null)
  const [menuPos, setMenuPos] = useState({ top: 0, left: 0 })

  useEffect(() => {
    if (!showSessionMenu) return
    function handleClick(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setShowSessionMenu(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [showSessionMenu])

  // Compute menu position from button ref when opening
  useEffect(() => {
    if (!showSessionMenu || !btnRef.current) return
    const rect = btnRef.current.getBoundingClientRect()
    setMenuPos({
      top: rect.bottom + 4,
      right: window.innerWidth - rect.right,
    })
  }, [showSessionMenu])

  const subtitle = phaseSubtitle(phase)

  return (
    <div className="flex items-center justify-between px-4 py-3 border-b border-neutral-100 bg-white/60 backdrop-blur-xl">
      <div className="flex items-center gap-3 min-w-0">
        <div className="flex-shrink-0 w-9 h-9 rounded-xl bg-gradient-to-br from-violet-100 to-orange-50 ring-1 ring-violet-100/50 flex items-center justify-center">
          <Search className="w-4 h-4 text-violet-500" />
        </div>
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-neutral-900 leading-tight truncate">
            {title}
          </h3>
          <p className="text-[11px] text-neutral-400 truncate">{subtitle}</p>
        </div>
      </div>

      <div className="flex items-center gap-0.5 flex-shrink-0">
        {/* Session history dropdown — trigger button */}
        {sessions.length > 0 && (
          <div ref={btnRef}>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => setShowSessionMenu(!showSessionMenu)}
              aria-label="历史会话"
              title="切换会话"
              className="text-neutral-400 hover:text-violet-500 h-7 w-7 rounded-lg"
            >
              <History className="h-3.5 w-3.5" />
            </Button>

            {/* Dropdown via portal — escapes overflow-hidden */}
            {showSessionMenu && typeof document !== 'undefined' && createPortal(
              <div
                ref={menuRef}
                className="fixed w-64 bg-white rounded-xl shadow-xl border border-neutral-100 py-1.5 z-[60] max-h-56 overflow-y-auto animate-message-pop-in"
                style={{
                  top: `${menuPos.top}px`,
                  right: `${menuPos.right}px`,
                }}
              >
                <div className="px-3 py-1.5">
                  <p className="text-[10px] text-neutral-400 uppercase tracking-wider font-medium">
                    历史会话
                  </p>
                </div>
                {sessions.map(s => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => {
                      onSelectSession(s.id)
                      setShowSessionMenu(false)
                    }}
                    className={`w-full text-left px-3 py-2 text-xs hover:bg-violet-50/50 transition-colors truncate
                      ${activeSessionId === s.id
                        ? 'text-violet-700 font-medium bg-violet-50/50'
                        : 'text-neutral-600'
                      }`}
                  >
                    {s.title || `研究 · ${s.id.slice(0, 8)}`}
                  </button>
                ))}
              </div>,
              document.body
            )}
          </div>
        )}
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={onNewSession}
          aria-label="新建研究"
          title="新建研究"
          className="text-neutral-400 hover:text-violet-500 h-7 w-7 rounded-lg"
        >
          <Plus className="h-4 w-4" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={onToggleFullscreen}
          aria-label={isFullscreen ? '退出全屏' : '全屏'}
          title={isFullscreen ? '退出全屏' : '全屏'}
          className="text-neutral-400 hover:text-violet-500 h-7 w-7 rounded-lg"
        >
          {isFullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={onClose}
          aria-label="关闭"
          title="关闭"
          className="text-neutral-400 hover:text-neutral-600 h-7 w-7 rounded-lg"
        >
          <X className="h-4 w-4" />
        </Button>
      </div>
    </div>
  )
}

function phaseSubtitle(phase) {
  switch (phase) {
    case 'thinking':    return '正在思考…'
    case 'tool_calling': return '正在调用工具…'
    case 'streaming':   return '正在生成回答'
    case 'success':     return '研究完成 ✨'
    case 'error':       return '出了点问题'
    default:            return '深度新闻分析与研究'
  }
}
