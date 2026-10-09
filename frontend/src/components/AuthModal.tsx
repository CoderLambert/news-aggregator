import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { FormEvent, MouseEvent } from 'react'
import { X } from 'lucide-react'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useAuth } from '@/context/AuthContext'

type AuthMode = 'login' | 'register'

interface AuthModalProps {
  onClose: () => void
  onSuccess?: () => void
  allowRegister?: boolean
  loginTitle?: string
}

function readableError(error: unknown): string {
  if (error && typeof error === 'object' && 'response' in error) {
    const response = error.response
    if (response && typeof response === 'object' && 'data' in response) {
      const data = response.data
      if (data && typeof data === 'object' && 'error' in data && typeof data.error === 'string') return data.error
      if (typeof data === 'string' && data.trim()) return data
    }
  }
  return error instanceof Error && error.message ? error.message : '请求失败，请重试'
}

export default function AuthModal({ onClose, onSuccess, allowRegister = true, loginTitle = '登录小闻' }: AuthModalProps) {
  const { login, register } = useAuth()
  const [mode, setMode] = useState<AuthMode>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const onCloseRef = useRef(onClose)
  useEffect(() => { onCloseRef.current = onClose }, [onClose])

  useGSAP(() => {
    const backdrop = containerRef.current
    const content = backdrop?.querySelector<HTMLElement>('.auth-modal-content')
    if (!backdrop || !content) return
    gsap.from(backdrop, { opacity: 0, duration: 0.25, ease: 'power2.out' })
    gsap.from(content, { opacity: 0, scale: 0.96, y: 8, duration: 0.3, ease: 'power2.out' })
  }, { scope: containerRef, dependencies: [] })

  useLayoutEffect(() => {
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
    let mounted = true
    queueMicrotask(() => {
      if (mounted) containerRef.current?.querySelector<HTMLInputElement>('#auth-username')?.focus()
    })

    function handleKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        onCloseRef.current()
        return
      }
      if (event.key !== 'Tab') return

      const dialog = containerRef.current
      const focusable = dialog?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
      )
      if (!focusable?.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (!dialog?.contains(document.activeElement)) {
        event.preventDefault()
        first.focus()
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      mounted = false
      document.removeEventListener('keydown', handleKeyDown)
      previousFocus?.focus()
    }
  }, [])

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      if (mode === 'login') await login(username, password)
      else await register(username, password, email)
      const finishAuthentication = onSuccess ?? onClose
      finishAuthentication()
    } catch (submitError) {
      setError(readableError(submitError))
    } finally {
      setSubmitting(false)
    }
  }

  function handleBackdropClick(event: MouseEvent<HTMLDivElement>) {
    if (event.target === event.currentTarget) onClose()
  }

  return (
    <div
      ref={containerRef}
      className="auth-modal-backdrop fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm"
      onClick={handleBackdropClick}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="auth-modal-title"
        aria-describedby={error ? 'auth-modal-error' : undefined}
        className="auth-modal-content w-full max-w-sm rounded-xl border border-border bg-card p-6 text-card-foreground shadow-xl"
      >
        <div className="mb-5 flex items-center justify-between gap-4">
          <h2 id="auth-modal-title" className="text-lg font-semibold">
            {mode === 'login' ? loginTitle : '注册小闻'}
          </h2>
          <Button type="button" variant="ghost" size="icon" onClick={onClose} aria-label="关闭登录窗口">
            <X aria-hidden="true" />
          </Button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {error && <p id="auth-modal-error" role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}

          <div className="space-y-1.5">
            <label htmlFor="auth-username" className="text-sm font-medium">用户名</label>
            <Input
              id="auth-username"
              value={username}
              onChange={(event) => setUsername(event.currentTarget.value)}
              placeholder="输入用户名"
              required
              autoComplete="username"
            />
          </div>

          {mode === 'register' && (
            <div className="space-y-1.5">
              <label htmlFor="auth-email" className="text-sm font-medium">邮箱（可选）</label>
              <Input
                id="auth-email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.currentTarget.value)}
                placeholder="user@example.com"
                autoComplete="email"
              />
            </div>
          )}

          <div className="space-y-1.5">
            <label htmlFor="auth-password" className="text-sm font-medium">密码</label>
            <Input
              id="auth-password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.currentTarget.value)}
              placeholder={mode === 'register' ? '至少 6 位' : '输入密码'}
              required
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            />
          </div>

          <Button type="submit" disabled={submitting || !username || !password} className="w-full">
            {submitting ? '处理中…' : mode === 'login' ? '登录' : '注册'}
          </Button>
        </form>

        {allowRegister ? <p className="mt-4 text-center text-sm text-muted-foreground">
          {mode === 'login' ? '还没有账号？' : '已有账号？'}{' '}
          <Button
            type="button"
            variant="link"
            size="sm"
            className="h-auto p-0 text-primary"
            onClick={() => {
              setMode((current) => current === 'login' ? 'register' : 'login')
              setError('')
            }}
          >
            {mode === 'login' ? '立即注册' : '去登录'}
          </Button>
        </p> : <p className="mt-4 text-center text-sm text-muted-foreground">公开注册只创建普通账号；管理员账号由部署者创建或授权。</p>}
      </section>
    </div>
  )
}
