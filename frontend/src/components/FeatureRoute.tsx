import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useCapability, capabilityReasonMessage } from '@/context/CapabilitiesContext'
import { useAuth } from '@/context/AuthContext'
import type { CapabilityName } from '@/services/api'

export default function FeatureRoute({
  feature,
  children,
  requireSuperuser = false,
}: {
  feature: CapabilityName
  children: ReactNode
  requireSuperuser?: boolean
}) {
  const capability = useCapability(feature)
  const { user, loading } = useAuth()

  if (!capability.enabled) return (
    <section className="mx-auto max-w-2xl px-4 py-16 text-center" role="status">
      <h1 className="text-xl font-semibold">暂不可用</h1>
      <p className="mt-2 text-sm text-muted-foreground">{capabilityReasonMessage(capability.reason)}</p>
      <Link to="/" className="mt-5 inline-flex min-h-11 items-center rounded-md px-4 text-sm font-medium text-primary underline underline-offset-4">
        返回首页
      </Link>
    </section>
  )

  if (requireSuperuser && loading) {
    return <p className="mx-auto max-w-2xl px-4 py-16 text-center text-sm text-muted-foreground" role="status">正在确认管理员权限…</p>
  }
  if (requireSuperuser && !user?.isSuperuser) {
    return <section className="mx-auto max-w-2xl px-4 py-16 text-center" role="status">
      <h1 className="text-xl font-semibold">无权访问</h1>
      <p className="mt-2 text-sm text-muted-foreground">此页面仅供管理员使用。</p>
      <Link to="/" className="mt-5 inline-flex min-h-11 items-center rounded-md px-4 text-sm font-medium text-primary underline underline-offset-4">
        返回首页
      </Link>
    </section>
  }
  return children
}
