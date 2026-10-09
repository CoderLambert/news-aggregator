import { useEffect, useRef, useState } from 'react'
import type { LucideIcon } from 'lucide-react'
import { AlignLeft, GitCompareArrows, Heart, House, Languages, LogOut, Menu, Search, Settings, Type, X } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import AuthModal from '@/components/AuthModal'
import { useAuth } from '@/context/AuthContext'
import { useLanguage } from '@/context/useLanguage'
import type { DisplayMode } from '@/types/news'

const DISPLAY_MODES = [
  { key: 'zh', label: '中文', icon: Type, color: 'text-orange-500' },
  { key: 'original', label: '原文', icon: Languages, color: 'text-blue-500' },
  { key: 'bilingual', label: '双文', icon: AlignLeft, color: 'text-violet-500' },
] satisfies ReadonlyArray<{ key: DisplayMode; label: string; icon: LucideIcon; color: string }>

export default function Header() {
  const { displayMode, setDisplayMode, t } = useLanguage()
  const { user, logout } = useAuth()
  const [showAuthModal, setShowAuthModal] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLElement | null>(null)
  const menuButtonRef = useRef<HTMLButtonElement | null>(null)
  const location = useLocation()

  useEffect(() => {
    if (!menuOpen) return
    const handlePointerDown = (event: PointerEvent) => {
      if (!(event.target instanceof Node)) return
      if (menuRef.current?.contains(event.target) || menuButtonRef.current?.contains(event.target)) return
      setMenuOpen(false)
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setMenuOpen(false)
        menuButtonRef.current?.focus()
      }
    }
    document.addEventListener('pointerdown', handlePointerDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [menuOpen])

  const currentMode = DISPLAY_MODES.find((mode) => mode.key === displayMode) ?? DISPLAY_MODES[0]
  const CurrentModeIcon = currentMode.icon

  function cycleDisplayMode() {
    const currentIndex = DISPLAY_MODES.findIndex((mode) => mode.key === displayMode)
    setDisplayMode(DISPLAY_MODES[(currentIndex + 1) % DISPLAY_MODES.length].key)
  }

  const isCurrent = (path: string) => path === '/'
    ? location.pathname === '/'
    : location.pathname === path || location.pathname.startsWith(`${path}/`)

  return (
    <>
      <header className="sticky top-0 z-50 border-b border-border bg-background/90 text-foreground backdrop-blur-lg">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
          <Link to="/" className="flex min-h-11 items-center gap-2 rounded-sm text-lg font-bold tracking-tight focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <span aria-hidden="true" className="inline-flex size-7 items-center justify-center rounded-lg bg-gradient-to-br from-orange-400 to-pink-400 text-xs font-bold text-white shadow-sm">N</span>
            <span>NewsHub</span>
          </Link>

          <div className="flex items-center gap-1 sm:gap-2">
            <Button type="button" variant="ghost" size="icon" className="size-11" asChild>
              <Link to="/search" aria-label="本地搜索"><Search aria-hidden="true" /></Link>
            </Button>

            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={cycleDisplayMode}
              title={`显示模式：${currentMode.label}（点击切换）`}
              aria-label={`显示模式：${currentMode.label}，点击切换`}
              className="h-11 rounded-full px-2.5 text-xs"
            >
              <CurrentModeIcon aria-hidden="true" className={`size-3.5 ${currentMode.color}`} />
              {currentMode.label}
            </Button>

            {user && (
              <span
                role="img"
                aria-label={`${user.username}，已登录`}
                className="ml-1 inline-flex size-7 items-center justify-center rounded-full bg-gradient-to-br from-orange-400 to-pink-400 text-xs font-bold text-white shadow-sm"
              >
                {user.username.charAt(0).toUpperCase()}
              </span>
            )}

            {!user && (
              <Button type="button" size="pill-sm" className="min-h-11" onClick={() => setShowAuthModal(true)}>
                登录
              </Button>
            )}

            <Button
              ref={menuButtonRef}
              type="button"
              variant="ghost"
              size="icon"
              className="size-11"
              aria-label={menuOpen ? '关闭菜单' : '打开菜单'}
              aria-expanded={menuOpen}
              aria-controls="site-navigation"
              onClick={() => setMenuOpen((open) => !open)}
            >
              {menuOpen ? <X aria-hidden="true" /> : <Menu aria-hidden="true" />}
            </Button>
          </div>
        </div>

        {menuOpen && (
          <nav
            ref={menuRef}
            id="site-navigation"
            aria-label="站点导航"
            className="absolute right-3 top-[calc(100%-4px)] z-50 w-60 overflow-hidden rounded-xl border border-border bg-popover p-2 text-popover-foreground shadow-xl"
          >
            <p className="px-3 pb-1 pt-2 text-xs font-medium text-muted-foreground">主要导航</p>
            {([
              { to: '/', label: '首页', icon: House },
              { to: '/search', label: '搜索', icon: Search },
              { to: '/favorites', label: '内容偏好', icon: Heart },
              { to: '/settings', label: '设置', icon: Settings },
            ] as const).map((item) => {
              const Icon = item.icon
              return (
                <Button key={item.to} variant={isCurrent(item.to) ? 'secondary' : 'ghost'} className="h-11 w-full justify-start" asChild>
                  <Link to={item.to} aria-current={isCurrent(item.to) ? 'page' : undefined} onClick={() => setMenuOpen(false)}>
                    <Icon aria-hidden="true" />{item.label}
                  </Link>
                </Button>
              )
            })}

            <div className="my-1 border-t border-border" />
            <p className="px-3 pb-1 pt-2 text-xs font-medium text-muted-foreground">工具</p>
            <Button variant={isCurrent('/provider-comparisons') ? 'secondary' : 'ghost'} className="h-11 w-full justify-start" asChild>
              <Link to="/provider-comparisons" aria-current={isCurrent('/provider-comparisons') ? 'page' : undefined} onClick={() => setMenuOpen(false)}>
                <GitCompareArrows aria-hidden="true" />Provider 对比
              </Link>
            </Button>
            <Button variant="ghost" className="h-11 w-full justify-start" asChild>
              <a href="/admin" target="_blank" rel="noreferrer" onClick={() => setMenuOpen(false)}>
                <Settings aria-hidden="true" />{t.admin}
              </a>
            </Button>

            {user && (
              <>
                <div className="my-1 border-t border-border" />
                <Button
                  type="button"
                  variant="ghost"
                  className="h-11 w-full justify-start text-destructive hover:text-destructive"
                  onClick={() => { void logout(); setMenuOpen(false) }}
                >
                  <LogOut aria-hidden="true" />退出登录
                </Button>
              </>
            )}
          </nav>
        )}
      </header>

      {showAuthModal && <AuthModal onClose={() => setShowAuthModal(false)} />}
    </>
  )
}
