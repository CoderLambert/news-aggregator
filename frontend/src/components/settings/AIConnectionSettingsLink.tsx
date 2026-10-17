import { Link } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'
import { useCapability } from '@/context/CapabilitiesContext'

export default function AIConnectionSettingsLink() {
  const { user } = useAuth()
  const { enabled } = useCapability('accounts')
  if (!user || !enabled) return null
  return <section className="mx-auto mb-8 max-w-5xl px-4" aria-label="多连接管理">
    <Link className="workspace-button secondary" to="/settings/ai">管理多个 AI 连接</Link>
    <p className="mt-2 text-sm text-muted-foreground">独立管理连接的名称、启停与密钥；现有单 Key 设置保持不变。</p>
  </section>
}
