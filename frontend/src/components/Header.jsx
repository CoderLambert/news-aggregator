import { useState, useRef, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { Heart, LogOut, Menu, X, Settings, Languages, Type, AlignLeft, GitCompareArrows } from 'lucide-react'
import { useLanguage } from '../context/useLanguage'
import { useAuth } from '../context/AuthContext'
import AuthModal from './AuthModal'

const DISPLAY_MODES = [
  { key: 'zh',        label: '中文',   icon: Type,      color: 'text-orange-400' },
  { key: 'original',  label: '原文',   icon: Languages,  color: 'text-blue-400' },
  { key: 'bilingual', label: '双文',   icon: AlignLeft,  color: 'text-purple-400' },
]

export default function Header() {
  const { lang, setLang, displayMode, setDisplayMode, t } = useLanguage()
  const { user, logout } = useAuth()
  const [showAuthModal, setShowAuthModal] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef(null)

  // 点击外部关闭菜单
  useEffect(() => {
    if (!menuOpen) return
    function handleClick(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('touchstart', handleClick, { passive: true })
    document.addEventListener('mousedown', handleClick)
    return () => {
      document.removeEventListener('touchstart', handleClick)
      document.removeEventListener('mousedown', handleClick)
    }
  }, [menuOpen])

  const currentMode = DISPLAY_MODES.find(m => m.key === displayMode) || DISPLAY_MODES[0]

  return (
    <>
      <header className="bg-white/80 backdrop-blur-lg border-b border-gray-100 sticky top-0 z-50">
        <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
          {/* Logo */}
          <Link to="/" className="text-lg font-bold text-gray-900 tracking-tight flex items-center gap-2">
            <span className="inline-flex items-center justify-center w-7 h-7 rounded-lg bg-gradient-to-br from-orange-400 to-pink-400 text-white text-xs font-bold shadow-sm">
              N
            </span>
            <span>NewsHub</span>
          </Link>

          {/* 右侧操作区 */}
          <div className="flex items-center gap-2">
            {/* 显示模式快捷切换 */}
            <button
              onClick={() => {
                const modes = DISPLAY_MODES.map(m => m.key)
                const idx = modes.indexOf(displayMode)
                setDisplayMode(modes[(idx + 1) % modes.length])
              }}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-full text-xs font-medium border border-gray-200 hover:border-gray-300 active:scale-95 transition-all"
              title={`显示模式：${currentMode.label}（点击切换）`}
            >
              <currentMode.icon className={`w-3.5 h-3.5 ${currentMode.color}`} />
              <span className="text-gray-600">{currentMode.label}</span>
            </button>

            {/* 已登录：用户头像 */}
            {user && (
              <div className="flex items-center gap-1.5 mr-1">
                <span className="w-7 h-7 rounded-full bg-gradient-to-br from-orange-400 to-pink-400 text-white text-xs font-bold flex items-center justify-center shadow-sm">
                  {user.username.charAt(0).toUpperCase()}
                </span>
              </div>
            )}

            {/* 未登录：登录按钮 */}
            {!user && (
              <button
                onClick={() => setShowAuthModal(true)}
                className="px-3 py-1.5 rounded-full text-xs font-medium text-white bg-gradient-to-r from-orange-400 to-pink-400 hover:from-orange-500 hover:to-pink-500 transition-all shadow-sm active:scale-95"
              >
                登录
              </button>
            )}

            {/* 菜单按钮 */}
            <button
              onClick={() => setMenuOpen(v => !v)}
              className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-gray-100 active:bg-gray-200 transition-colors"
              aria-label="菜单"
            >
              {menuOpen ? <X className="w-4.5 h-4.5 text-gray-600" /> : <Menu className="w-4.5 h-4.5 text-gray-600" />}
            </button>
          </div>
        </div>

        {/* 下拉菜单 */}
        {menuOpen && (
          <div
            ref={menuRef}
            className="absolute right-3 top-[calc(100%-4px)] w-56 bg-white rounded-2xl shadow-xl border border-gray-100 py-2 z-50 overflow-hidden"
          >
            {/* 收藏 */}
            <Link
              to="/favorites"
              onClick={() => setMenuOpen(false)}
              className="flex items-center gap-3 px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 active:bg-gray-100 transition-colors"
            >
              <Heart className="w-4 h-4 text-pink-400" />
              我的收藏
            </Link>

            <Link
              to="/provider-comparisons"
              onClick={() => setMenuOpen(false)}
              className="flex items-center gap-3 px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 active:bg-gray-100 transition-colors"
            >
              <GitCompareArrows className="w-4 h-4 text-indigo-400" />
              Provider 对比
            </Link>

            {/* 显示模式 */}
            <div className="px-4 py-2">
              <p className="text-[11px] text-gray-400 uppercase tracking-wider font-medium mb-2">显示模式</p>
              <div className="flex gap-1.5">
                {DISPLAY_MODES.map(mode => (
                  <button
                    key={mode.key}
                    onClick={() => { setDisplayMode(mode.key); setMenuOpen(false) }}
                    className={`
                      flex-1 flex flex-col items-center gap-0.5 py-2 rounded-xl text-xs font-medium transition-all
                      ${displayMode === mode.key
                        ? 'bg-gray-900 text-white shadow-sm'
                        : 'bg-gray-50 text-gray-500 hover:bg-gray-100 active:bg-gray-200'
                      }
                    `}
                  >
                    <mode.icon className="w-3.5 h-3.5" />
                    {mode.label}
                  </button>
                ))}
              </div>
            </div>

            {/* UI 语言切换 */}
            <button
              onClick={() => { setLang(lang === 'zh' ? 'en' : 'zh'); setMenuOpen(false) }}
              className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 active:bg-gray-100 transition-colors"
            >
              <Languages className="w-4 h-4 text-blue-400" />
              界面语言：{lang === 'zh' ? '中文' : 'English'}
            </button>

            {/* 管理后台 */}
            <a
              href="/admin"
              target="_blank"
              rel="noreferrer"
              onClick={() => setMenuOpen(false)}
              className="flex items-center gap-3 px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 active:bg-gray-100 transition-colors"
            >
              <Settings className="w-4 h-4 text-gray-400" />
              {t.admin}
            </a>

            {/* 已登录：退出 */}
            {user && (
              <>
                <div className="my-1 border-t border-gray-100" />
                <button
                  onClick={() => { logout(); setMenuOpen(false) }}
                  className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-red-500 hover:bg-red-50 active:bg-red-100 transition-colors"
                >
                  <LogOut className="w-4 h-4" />
                  退出登录
                </button>
              </>
            )}
          </div>
        )}
      </header>

      {showAuthModal && (
        <AuthModal onClose={() => setShowAuthModal(false)} />
      )}
    </>
  )
}
