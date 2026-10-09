import { useEffect, useId, useState } from 'react'
import { useNearViewport } from '@/hooks/useNearViewport'

function errorMessage(error: unknown): string {
  return error instanceof Error && error.message ? error.message : 'Mermaid render failed'
}

export default function MermaidBlock({ code }: { code: string }) {
  const reactId = useId()
  const [html, setHtml] = useState('')
  const [error, setError] = useState<string | null>(null)
  const renderId = `mermaid-${reactId.replace(/[^a-zA-Z0-9_-]/g, '')}`
  const { targetRef, isNearViewport } = useNearViewport<HTMLDivElement>()

  useEffect(() => {
    let cancelled = false

    async function render() {
      try {
        const mermaid = (await import('mermaid')).default
        mermaid.initialize({
          startOnLoad: false,
          theme: 'default',
          securityLevel: 'loose',
          fontFamily: 'inherit',
        })
        const { svg } = await mermaid.render(renderId, code)
        if (!cancelled) {
          setHtml(svg)
          setError(null)
        }
      } catch (renderError) {
        if (!cancelled) {
          setError(errorMessage(renderError))
          setHtml('')
        }
      }
    }

    if (!isNearViewport) return
    void render()
    return () => { cancelled = true }
  }, [code, isNearViewport, renderId])

  if (error) {
    return (
      <div role="alert" className="my-4 rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
        <p className="mb-2 font-medium">Mermaid 图表渲染失败</p>
        <pre className="overflow-x-auto whitespace-pre-wrap text-xs text-muted-foreground">{code}</pre>
      </div>
    )
  }

  if (!html) {
    return (
      <div ref={targetRef} role="status" aria-live="polite" className="my-4 flex items-center justify-center rounded-md border border-border bg-muted p-6">
        <span className="text-sm text-muted-foreground">{isNearViewport ? '渲染图表中…' : '滚动到附近时渲染图表'}</span>
      </div>
    )
  }

  return (
    <div
      role="img"
      aria-label="Mermaid 图表"
      className="my-4 flex justify-center overflow-x-auto rounded-md border border-border bg-card p-4"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}
