import { Link } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'
import { useCapability } from '@/context/CapabilitiesContext'

export default function AIConnectionSettingsLink() {
  const { user } = useAuth()
  const { enabled } = useCapability('accounts')
  if (!user || !enabled) return null
  return <section className="mx-auto mb-8 max-w-5xl px-4" aria-label="多连接管理">
    <Link className="workspace-button secondary" to="/settings/ai">管理个人 AI 连接</Link>
    <p className="mt-2 text-sm text-muted-foreground">统一管理个人服务商连接、密钥与启停状态。模型与用途设置将在后续批次开放。</p>
  </section>
}
