import { Activity, SearchCheck, ShieldCheck } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'

const NAVIGATION = [
  { href: '#overview', label: '运行概览', icon: Activity },
  { href: '#search-index', label: '搜索索引', icon: SearchCheck },
] as const

export default function AdminLayout({ children }: { children: ReactNode }) {
  const [activeSection, setActiveSection] = useState(() => window.location.hash || '#overview')

  useEffect(() => {
    const syncHash = () => setActiveSection(window.location.hash || '#overview')
    window.addEventListener('hashchange', syncHash)
    return () => window.removeEventListener('hashchange', syncHash)
  }, [])

  return (
    <div className="admin-workspace">
      <div className="mx-auto max-w-[1280px] px-4 pb-10 sm:px-6 lg:px-8">
        <div className="admin-intro">
          <span className="admin-access-badge"><ShieldCheck aria-hidden="true" className="size-3.5" />仅限超级管理员</span>
          <p>查看 RSS 同步状态，管理搜索索引。</p>
        </div>
        <nav aria-label="管理页面分区" className="admin-section-nav workspace-scroll">
          {NAVIGATION.map(({ href, label, icon: Icon }) => (
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
