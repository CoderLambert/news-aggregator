import { useAuth } from '@/context/AuthContext'
import { Activity, SearchCheck, ShieldCheck } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'

const NAVIGATION = [
  { href: '/admin/rss#overview', label: '运行概览', icon: Activity },
  { href: '/admin/rss/recommendations', label: '公开频道审核', icon: ShieldCheck },
  { href: '/admin/rss/reviewers', label: '频道审核员', icon: ShieldCheck },
  { href: '/admin/rss/channels', label: '频道核验', icon: ShieldCheck },
  { href: '/admin/rss#search-index', label: '搜索索引', icon: SearchCheck },
] as const

export default function AdminLayout({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  const [activeSection, setActiveSection] = useState(() => window.location.pathname + (window.location.hash || (window.location.pathname === '/admin/rss' ? '#overview' : '')))

  useEffect(() => {
    const syncHash = () => setActiveSection(window.location.pathname + (window.location.hash || (window.location.pathname === '/admin/rss' ? '#overview' : '')))
    window.addEventListener('hashchange', syncHash)
    return () => window.removeEventListener('hashchange', syncHash)
  }, [])

  return (
    <div className="admin-workspace">
      <div className="mx-auto max-w-[1280px] px-4 pb-10 sm:px-6 lg:px-8">
        <div className="admin-intro">
          <span className="admin-access-badge"><ShieldCheck aria-hidden="true" className="size-3.5" />{user?.isSuperuser ? '仅限超级管理员' : '频道审核员'}</span>
          <p>{user?.isSuperuser ? '管理公共频道、审核权限和运行状态。' : '审核公开推荐，处理频道连接。'}</p>
        </div>
        <nav aria-label="管理页面分区" className="admin-section-nav workspace-scroll">
          {NAVIGATION.filter(item => user?.isSuperuser || ['/admin/rss/channels', '/admin/rss/recommendations'].includes(item.href)).map(({ href, label, icon: Icon }) => (
            <a key={href} href={href} aria-current={activeSection === href ? 'location' : undefined}
              onClick={() => setActiveSection(href)} className="admin-section-link">
              <Icon aria-hidden="true" className="size-4" />{label}
            </a>
          ))}
        </nav>
        {children}
      </div>
    </div>
  )
}
