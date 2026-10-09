import { useEffect, useId, useState } from 'react'
import DOMPurify from 'dompurify'
import { useNearViewport } from '@/hooks/useNearViewport'

const MAX_MERMAID_TEXT_SIZE = 20_000
const SECURE_MERMAID_CONFIG_KEYS = [
  'securityLevel',
  'startOnLoad',
  'maxTextSize',
  'maxEdges',
  'htmlLabels',
  'flowchart',
  'themeCSS',
  'themeVariables',
  'secure',
]

const SVG_SANITIZE_OPTIONS = {
  USE_PROFILES: { svg: true, svgFilters: true },
  FORBID_TAGS: ['foreignObject', 'script', 'iframe', 'object', 'embed', 'style', 'a', 'image', 'use'],
  FORBID_ATTR: ['href', 'xlink:href', 'style'],
  RETURN_TRUSTED_TYPE: false,
}

type RenderState = {
  code: string
  html: string
  error: string | null
}

function errorMessage(error: unknown): string {
  return error instanceof Error && error.message ? error.message : 'Mermaid render failed'
}

export default function MermaidBlock({ code }: { code: string }) {
  const reactId = useId()
  const [renderState, setRenderState] = useState<RenderState | null>(null)
  const renderId = `mermaid-${reactId.replace(/[^a-zA-Z0-9_-]/g, '')}`
  const { targetRef, isNearViewport } = useNearViewport<HTMLDivElement>()
  const isOversized = code.length > MAX_MERMAID_TEXT_SIZE
  const currentRender = renderState?.code === code ? renderState : null

  useEffect(() => {
    let cancelled = false

    async function render() {
      try {
        const mermaid = (await import('mermaid')).default
        mermaid.initialize({
          startOnLoad: false,
          theme: 'default',
          securityLevel: 'strict',
          fontFamily: 'inherit',
          htmlLabels: false,
          flowchart: { htmlLabels: false },
          maxTextSize: MAX_MERMAID_TEXT_SIZE,
          maxEdges: 500,
          secure: [...SECURE_MERMAID_CONFIG_KEYS],
        })
        const { svg } = await mermaid.render(renderId, code)
        const safeSvg = DOMPurify.sanitize(svg, SVG_SANITIZE_OPTIONS)
        if (!safeSvg.trim()) throw new Error('Diagram output was removed by the SVG safety filter')
        if (!cancelled) {
          setRenderState({ code, html: safeSvg, error: null })
        }
      } catch (renderError) {
        if (!cancelled) {
          setRenderState({ code, html: '', error: errorMessage(renderError) })
        }
      }
    }

    if (!isNearViewport || isOversized) return
    void render()
    return () => { cancelled = true }
  }, [code, isNearViewport, isOversized, renderId])

  if (isOversized) {
    return (
      <div role="alert" className="my-4 rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
        <p className="mb-2 font-medium">Mermaid 图表超过安全长度限制，无法渲染</p>
        <pre className="overflow-x-auto whitespace-pre-wrap text-xs text-muted-foreground">{code}</pre>
      </div>
    )
  }

  if (currentRender?.error) {
    return (
      <div role="alert" className="my-4 rounded-md border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
        <p className="mb-2 font-medium">Mermaid 图表渲染失败</p>
        <pre className="overflow-x-auto whitespace-pre-wrap text-xs text-muted-foreground">{code}</pre>
      </div>
    )
  }

  if (!currentRender?.html) {
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
      dangerouslySetInnerHTML={{ __html: currentRender.html }}
    />
  )
}
