import { useRef, useEffect, useState } from 'react'

/**
 * MermaidBlock — lazy-renders a Mermaid diagram.
 *
 * The mermaid library is ~2MB gzipped. We dynamically import it only when
 * a ````mermaid` code block is actually encountered, so the base bundle
 * stays lean.
 */
export default function MermaidBlock({ code }) {
  const containerRef = useRef(null)
  const [html, setHtml] = useState('')
  const [error, setError] = useState(null)

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
        const id = `mermaid-${Math.random().toString(36).slice(2, 10)}`
        const { svg } = await mermaid.render(id, code)
        if (!cancelled) {
          setHtml(svg)
          setError(null)
        }
      } catch (err) {
        if (!cancelled) {
          setError(err.message || 'Mermaid render failed')
          setHtml('')
        }
      }
    }

    render()
    return () => { cancelled = true }
  }, [code])

  if (error) {
    return (
      <div className="my-4 p-4 bg-red-50 border border-red-200 rounded-xl text-sm text-red-600">
        <p className="font-medium mb-1">Mermaid 图表渲染失败</p>
        <pre className="text-xs text-red-400 whitespace-pre-wrap">{code}</pre>
      </div>
    )
  }

  if (!html) {
    return (
      <div className="my-4 flex items-center justify-center p-6 bg-gray-50 rounded-xl border border-gray-200">
        <span className="text-sm text-gray-400">渲染图表中...</span>
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      className="my-4 flex justify-center overflow-x-auto bg-white rounded-xl border border-gray-200 p-4"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}
