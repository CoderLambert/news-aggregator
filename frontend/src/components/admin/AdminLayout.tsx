import { Activity, ArrowLeft, Database, History, SearchCheck } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

const NAVIGATION = [
  { href: '#overview', label: '运行概览', icon: Activity },
  { href: '#search-index', label: '搜索索引', icon: SearchCheck },
  { href: '#sources', label: '来源管理', icon: Database },
  { href: '#history', label: '抓取历史', icon: History },
] as const

export default function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-[calc(100vh-3.5rem)] bg-neutral-50/70">
      <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
        <div className="mb-6 flex flex-col gap-4 border-b border-border pb-5 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="mb-1 text-sm font-medium text-orange-600">仅限超级管理员</p>
            <h1 className="text-2xl font-bold tracking-tight sm:text-3xl">爬虫管理控制台</h1>
            <p className="mt-2 text-sm text-muted-foreground">控制 Docker 自动调度，查看每个来源的真实执行结果。</p>
          </div>
          <Link className="inline-flex min-h-11 items-center gap-2 rounded-md px-3 text-sm font-medium hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" to="/">
            <ArrowLeft aria-hidden="true" className="size-4" />返回新闻站点
          </Link>
        </div>
        <nav aria-label="管理页面分区" className="mb-6 flex gap-2 overflow-x-auto pb-1">
          {NAVIGATION.map(({ href, label, icon: Icon }) => (
            <a key={href} href={href} className="inline-flex min-h-10 shrink-0 items-center gap-2 rounded-full border bg-background px-4 text-sm font-medium hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
              <Icon aria-hidden="true" className="size-4" />{label}
            </a>
          ))}
        </nav>
        {children}
      </div>
    </div>
  )
}
