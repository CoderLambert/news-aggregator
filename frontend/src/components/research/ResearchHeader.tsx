import { useEffect, useRef, useState, type MouseEvent } from 'react'
import { createPortal } from 'react-dom'
import { History, Maximize2, Minimize2, Plus, Search, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { ResearchPhase, ResearchSessionSummary } from '@/types/research'

interface ResearchHeaderProps {
  title?: string
  phase: ResearchPhase
  isFullscreen: boolean
  onToggleFullscreen: () => void
  onNewSession: () => void
  onClose: () => void
  sessions: ResearchSessionSummary[]
  activeSessionId: string | null
  onSelectSession: (sessionId: string) => void
}

export default function ResearchHeader({
  title = '新闻研究',
  phase,
  isFullscreen,
  onToggleFullscreen,
  onNewSession,
  onClose,
  sessions,
  activeSessionId,
  onSelectSession,
}: ResearchHeaderProps) {
  const [showSessionMenu, setShowSessionMenu] = useState(false)
  const btnRef = useRef<HTMLDivElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const [menuPos, setMenuPos] = useState({ top: 0, right: 0 })
  const subtitle = phaseSubtitle(phase)

  useEffect(() => {
    if (!showSessionMenu) return
    function handleClick(event: globalThis.MouseEvent) {
      const target = event.target
      if (target instanceof Node && menuRef.current && !menuRef.current.contains(target)) {
        setShowSessionMenu(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [showSessionMenu])

  useEffect(() => {
    if (!showSessionMenu || !btnRef.current) return
    const rect = btnRef.current.getBoundingClientRect()
    setMenuPos({ top: rect.bottom + 4, right: window.innerWidth - rect.right })
  }, [showSessionMenu])

  function handleSelect(event: MouseEvent<HTMLButtonElement>, sessionId: string) {
    event.preventDefault()
    onSelectSession(sessionId)
    setShowSessionMenu(false)
  }

  return (
    <div className="flex items-center justify-between px-4 py-3 border-b border-neutral-100 bg-white/60 backdrop-blur-xl">
      <div className="flex items-center gap-3 min-w-0">
        <div className="flex-shrink-0 w-9 h-9 rounded-xl bg-gradient-to-br from-violet-100 to-orange-50 ring-1 ring-violet-100/50 flex items-center justify-center">
          <Search className="w-4 h-4 text-violet-500" />
        </div>
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-neutral-900 leading-tight truncate">{title}</h3>
          <p className="text-[11px] text-neutral-400 truncate">{subtitle}</p>
        </div>
      </div>

      <div className="flex items-center gap-0.5 flex-shrink-0">
        {sessions.length > 0 && (
          <div ref={btnRef}>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => setShowSessionMenu((open) => !open)}
              aria-label="历史会话"
              aria-haspopup="menu"
              aria-expanded={showSessionMenu}
              aria-controls="research-session-menu"
              title="切换会话"
              className="text-neutral-400 hover:text-violet-500 h-7 w-7 rounded-lg"
            >
              <History className="h-3.5 w-3.5" />
            </Button>

            {showSessionMenu && typeof document !== 'undefined' && createPortal(
              <div
                id="research-session-menu"
                ref={menuRef}
                role="menu"
                aria-label="历史会话"
                className="fixed w-64 bg-white rounded-xl shadow-xl border border-neutral-100 py-1.5 z-[60] max-h-56 overflow-y-auto animate-message-pop-in"
                style={{ top: `${menuPos.top}px`, right: `${menuPos.right}px` }}
              >
                <div className="px-3 py-1.5">
                  <p className="text-[10px] text-neutral-400 uppercase tracking-wider font-medium">历史会话</p>
                </div>
                {sessions.map((session) => (
                  <button
                    key={session.id}
                    type="button"
                    role="menuitem"
                    aria-current={activeSessionId === session.id ? 'true' : undefined}
                    onClick={(event) => handleSelect(event, session.id)}
                    className={`w-full text-left px-3 py-2 text-xs hover:bg-violet-50/50 transition-colors truncate
                      ${activeSessionId === session.id ? 'text-violet-700 font-medium bg-violet-50/50' : 'text-neutral-600'}`}
                  >
                    {session.title || `研究 · ${session.id.slice(0, 8)}`}
                  </button>
                ))}
              </div>,
              document.body,
            )}
          </div>
        )}
        <Button type="button" variant="ghost" size="icon" onClick={onNewSession} aria-label="新建研究" title="新建研究" className="text-neutral-400 hover:text-violet-500 h-7 w-7 rounded-lg">
          <Plus className="h-4 w-4" />
        </Button>
        <Button type="button" variant="ghost" size="icon" onClick={onToggleFullscreen} aria-label={isFullscreen ? '退出全屏' : '全屏'} title={isFullscreen ? '退出全屏' : '全屏'} className="text-neutral-400 hover:text-violet-500 h-7 w-7 rounded-lg">
          {isFullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
        </Button>
        <Button type="button" variant="ghost" size="icon" onClick={onClose} aria-label="关闭" title="关闭" className="text-neutral-400 hover:text-neutral-600 h-7 w-7 rounded-lg">
          <X className="h-4 w-4" />
        </Button>
      </div>
    </div>
  )
}

function phaseSubtitle(phase: ResearchPhase): string {
  switch (phase) {
    case 'thinking': return '正在思考…'
    case 'tool_calling': return '正在调用工具…'
    case 'streaming': return '正在生成回答'
    case 'success': return '研究完成 ✨'
    case 'cancelled': return '已停止接收'
    case 'error': return '出了点问题'
    default: return '深度新闻分析与研究'
  }
}
