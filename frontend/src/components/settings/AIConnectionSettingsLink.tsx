import { Link } from 'react-router-dom'
import { useAuth } from '@/context/AuthContext'
import { useCapability } from '@/context/CapabilitiesContext'

export default function AIConnectionSettingsLink() {
  const { user } = useAuth()
  const { enabled } = useCapability('accounts')
  if (!user || !enabled) return null
  return <section className="mx-auto mb-8 max-w-5xl px-4" aria-label="多连接管理">
    <Link className="workspace-button secondary" to="/settings/ai">管理个人 AI 连接</Link>
    <Link className="workspace-button secondary ml-2" to="/settings/ai/usage">AI 使用记录</Link>
    <p className="mt-2 text-sm text-muted-foreground">管理连接、模型和默认用途；在独立分页列表中查看调用记录。</p>
  </section>
}
