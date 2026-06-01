import { useState } from 'react'
import { X } from 'lucide-react'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'
import { useAuth } from '../context/AuthContext'

/**
 * AuthModal — Apple 风格登录/注册弹窗
 *
 * 轻量级 Session Auth：支持用户名+密码的注册和登录。
 * 打开时自动获取 CSRF token 并设置到 axios 拦截器。
 */
export default function AuthModal({ onClose }) {
  const { login, register } = useAuth()
  const [mode, setMode] = useState('login') // login | register
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useGSAP(() => {
    gsap.from('.auth-modal-backdrop', {
      opacity: 0,
      duration: 0.25,
      ease: 'power2.out',
    })
    gsap.from('.auth-modal-content', {
      opacity: 0,
      scale: 0.92,
      y: 12,
      duration: 0.3,
      ease: 'back.out(1.4)',
    })
  })

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setSubmitting(true)

    try {
      if (mode === 'login') {
        await login(username, password)
      } else {
        await register(username, password, email)
      }
      onClose()
    } catch (err) {
      const msg = err?.response?.data?.error || err?.message || '请求失败，请重试'
      setError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="auth-modal-backdrop fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="auth-modal-content w-full max-w-sm rounded-2xl bg-white shadow-xl p-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-semibold text-neutral-900">
            {mode === 'login' ? '登录小闻' : '注册小闻'}
          </h2>
          <button
            onClick={onClose}
            className="p-1 rounded-full hover:bg-neutral-100 transition-colors"
          >
            <X className="size-4 text-neutral-500" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="text-sm text-red-500 bg-red-50 rounded-lg px-3 py-2">
              {error}
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-neutral-500 mb-1">用户名</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-3 py-2 text-sm rounded-xl border border-neutral-200 focus:border-orange-400 focus:ring-2 focus:ring-orange-100 outline-none transition-all"
              placeholder="输入用户名"
              required
              autoComplete="username"
            />
          </div>

          {mode === 'register' && (
            <div>
              <label className="block text-xs font-medium text-neutral-500 mb-1">邮箱（可选）</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-3 py-2 text-sm rounded-xl border border-neutral-200 focus:border-orange-400 focus:ring-2 focus:ring-orange-100 outline-none transition-all"
                placeholder="user@example.com"
              />
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-neutral-500 mb-1">密码</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-2 text-sm rounded-xl border border-neutral-200 focus:border-orange-400 focus:ring-2 focus:ring-orange-100 outline-none transition-all"
              placeholder={mode === 'register' ? '至少 6 位' : '输入密码'}
              required
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            />
          </div>

          <button
            type="submit"
            disabled={submitting || !username || !password}
            className="w-full py-2.5 rounded-xl text-sm font-medium text-white bg-gradient-to-r from-orange-400 to-pink-400 hover:from-orange-500 hover:to-pink-500 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-md hover:shadow-lg active:scale-[0.97]"
          >
            {submitting ? '处理中...' : mode === 'login' ? '登录' : '注册'}
          </button>
        </form>

        {/* Toggle */}
        <p className="text-xs text-neutral-400 text-center mt-4">
          {mode === 'login' ? '还没有账号？' : '已有账号？'}{' '}
          <button
            onClick={() => {
              setMode(mode === 'login' ? 'register' : 'login')
              setError('')
            }}
            className="text-orange-500 hover:text-orange-600 font-medium"
          >
            {mode === 'login' ? '立即注册' : '去登录'}
          </button>
        </p>
      </div>
    </div>
  )
}
