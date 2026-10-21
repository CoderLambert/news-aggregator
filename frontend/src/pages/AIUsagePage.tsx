import { Link } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'
import AIUsageSection from '@/components/workspace/AIUsageSection'

export default function AIUsagePage() {
  const { user, loading } = useAuth()
  if (loading) return <p role="status" className="workspace-empty">正在读取账号…</p>
  return <div className="workspace-page min-w-0">
    <Link to="/settings/ai" className="workspace-link">返回个人 AI 连接</Link>
    <header className="workspace-page-heading"><h1>AI 使用记录</h1></header>
    {user ? <AIUsageSection key={user.id} viewer={user.id} />
      : <p>请先<Link to="/settings/ai" className="workspace-link">登录账号</Link>查看自己的使用记录。</p>}
  </div>
}
