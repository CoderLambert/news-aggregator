import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useCapability, capabilityReasonMessage } from '@/context/CapabilitiesContext'
import type { CapabilityName } from '@/services/api'

export default function FeatureRoute({ feature, children }: { feature: CapabilityName; children: ReactNode }) {
  const capability = useCapability(feature)
  if (capability.enabled) return children

  return (
    <section className="mx-auto max-w-2xl px-4 py-16 text-center" role="status">
      <h1 className="text-xl font-semibold">暂不可用</h1>
      <p className="mt-2 text-sm text-muted-foreground">{capabilityReasonMessage(capability.reason)}</p>
      <Link to="/" className="mt-5 inline-flex min-h-11 items-center rounded-md px-4 text-sm font-medium text-primary underline underline-offset-4">
        返回首页
      </Link>
    </section>
  )
}
