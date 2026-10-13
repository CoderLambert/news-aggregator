import { useEffect, useRef, useState, type KeyboardEvent, type MouseEvent } from 'react'
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
  const [focusedMenuIndex, setFocusedMenuIndex] = useState(0)
  const btnRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const menuItemRefs = useRef<Array<HTMLButtonElement | null>>([])
  const pendingOpenFocus = useRef<number | null>(null)
  const [menuPos, setMenuPos] = useState({ top: 0, right: 0 })
  const subtitle = phaseSubtitle(phase)

  useEffect(() => {
    if (!showSessionMenu) return
    function handleClick(event: globalThis.MouseEvent) {
      const target = event.target
      if (
        target instanceof Node && menuRef.current && !menuRef.current.contains(target) &&
        !triggerRef.current?.contains(target)
      ) {
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

  useEffect(() => {
    if (!showSessionMenu || !sessions.length) return
    const selectedIndex = sessions.findIndex((session) => session.id === activeSessionId)
    const index = pendingOpenFocus.current ?? (selectedIndex >= 0 ? selectedIndex : 0)
    pendingOpenFocus.current = null
    setFocusedMenuIndex(index)
    menuItemRefs.current[index]?.focus()
  }, [activeSessionId, sessions, showSessionMenu])

  function focusMenuItem(index: number) {
    if (!sessions.length) return
    const nextIndex = (index + sessions.length) % sessions.length
    setFocusedMenuIndex(nextIndex)
    menuItemRefs.current[nextIndex]?.focus()
  }

  function openSessionMenu(index?: number) {
    const selectedIndex = sessions.findIndex((session) => session.id === activeSessionId)
    pendingOpenFocus.current = index ?? (selectedIndex >= 0 ? selectedIndex : 0)
    setShowSessionMenu(true)
  }

  function handleTriggerKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      openSessionMenu(0)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      openSessionMenu(sessions.length - 1)
    }
  }

  function handleMenuKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!sessions.length) return
    if (event.key === 'Escape') {
      event.preventDefault()
      setShowSessionMenu(false)
      triggerRef.current?.focus()
      return
    }
    if (event.key === 'Tab') {
      window.setTimeout(() => setShowSessionMenu(false), 0)
      return
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      focusMenuItem(focusedMenuIndex + 1)
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      focusMenuItem(focusedMenuIndex - 1)
    } else if (event.key === 'Home') {
      event.preventDefault()
      focusMenuItem(0)
    } else if (event.key === 'End') {
      event.preventDefault()
      focusMenuItem(sessions.length - 1)
    }
  }

  function handleSelect(event: MouseEvent<HTMLButtonElement>, sessionId: string) {
    event.preventDefault()
    onSelectSession(sessionId)
    setShowSessionMenu(false)
    triggerRef.current?.focus()
  }

  return (
    <div className="flex items-center justify-between border-b border-border bg-card/90 px-4 py-3 backdrop-blur-xl">
      <div className="flex items-center gap-3 min-w-0">
        <div className="flex size-9 flex-shrink-0 items-center justify-center rounded-xl bg-primary/10 ring-1 ring-primary/15">
          <Search className="size-4 text-primary" />
        </div>
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold leading-tight text-foreground">{title}</h3>
          <p className="truncate text-[11px] text-muted-foreground">{subtitle}</p>
        </div>
      </div>

      <div className="flex items-center gap-0.5 flex-shrink-0">
        {sessions.length > 0 && (
          <div ref={btnRef}>
            <Button
              ref={triggerRef}
              type="button"
              variant="ghost"
              size="icon"
              onClick={() => setShowSessionMenu((open) => !open)}
              onKeyDown={handleTriggerKeyDown}
              aria-label="历史会话"
              aria-haspopup="menu"
              aria-expanded={showSessionMenu}
              aria-controls="research-session-menu"
              title="切换会话"
              className="size-7 rounded-lg text-muted-foreground hover:bg-accent hover:text-primary"
            >
              <History className="h-3.5 w-3.5" />
            </Button>

            {showSessionMenu && typeof document !== 'undefined' && createPortal(
              <div
                id="research-session-menu"
                ref={menuRef}
                role="menu"
                aria-label="历史会话"
                onKeyDown={handleMenuKeyDown}
                className="fixed z-[60] max-h-56 w-64 overflow-y-auto rounded-xl border border-border bg-popover py-1.5 text-popover-foreground shadow-xl animate-message-pop-in"
                style={{ top: `${menuPos.top}px`, right: `${menuPos.right}px` }}
              >
                <div className="px-3 py-1.5">
                  <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">历史会话</p>
                </div>
                {sessions.map((session, index) => (
                  <button
                    key={session.id}
                    ref={(element) => { menuItemRefs.current[index] = element }}
                    type="button"
                    role="menuitem"
                    tabIndex={focusedMenuIndex === index ? 0 : -1}
                    onFocus={() => setFocusedMenuIndex(index)}
                    aria-current={activeSessionId === session.id ? 'true' : undefined}
                    onClick={(event) => handleSelect(event, session.id)}
                    className={`w-full truncate px-3 py-2 text-left text-xs transition-colors hover:bg-accent
                      ${activeSessionId === session.id ? 'bg-primary/10 font-medium text-primary' : 'text-muted-foreground'}`}
                  >
                    {session.title || `研究 · ${session.id.slice(0, 8)}`}
                  </button>
                ))}
              </div>,
              document.body,
            )}
          </div>
        )}
        <Button type="button" variant="ghost" size="icon" onClick={onNewSession} aria-label="新建研究" title="新建研究" className="size-7 rounded-lg text-muted-foreground hover:text-primary">
          <Plus className="h-4 w-4" />
        </Button>
        <Button type="button" variant="ghost" size="icon" onClick={onToggleFullscreen} aria-label={isFullscreen ? '退出全屏' : '全屏'} title={isFullscreen ? '退出全屏' : '全屏'} className="size-7 rounded-lg text-muted-foreground hover:text-primary">
          {isFullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
        </Button>
        <Button type="button" variant="ghost" size="icon" onClick={onClose} aria-label="关闭" title="关闭" className="size-7 rounded-lg text-muted-foreground hover:text-foreground">
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
