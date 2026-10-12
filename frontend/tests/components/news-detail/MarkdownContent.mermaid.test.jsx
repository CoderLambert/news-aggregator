import { act, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MarkdownContent from '@/components/news-detail/MarkdownContent'

const mermaidMock = vi.hoisted(() => ({
  initialize: vi.fn(),
  render: vi.fn(),
  bindFunctions: vi.fn(),
}))

vi.mock('mermaid', () => ({ default: mermaidMock }))

const SAFE_SVG = '<svg xmlns="http://www.w3.org/2000/svg"><text>diagram</text></svg>'

beforeEach(() => {
  vi.clearAllMocks()
  mermaidMock.render.mockResolvedValue({ svg: SAFE_SVG, bindFunctions: mermaidMock.bindFunctions })
})

describe('MarkdownContent Mermaid rendering', () => {
  it('keeps the source visible and announces a failed diagram render', async () => {
    mermaidMock.render.mockRejectedValueOnce(new Error('invalid diagram syntax'))
    const { container } = render(<MarkdownContent content={'```mermaid\ngraph TD\n  A --> B\n```'} />)

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Mermaid 图表渲染失败'))
    expect(screen.getByRole('alert')).toHaveTextContent('A --> B')
    expect(container.querySelector('.newshub-mermaid')).toBeNull()
  })

  it('sanitizes Mermaid SVG output with the real DOMPurify package', async () => {
    const hostileSvg = `
      <svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" onload="run()">
        <script>run()</script>
        <foreignObject><img src="x" onerror="run()" /></foreignObject>
        <iframe src="https://attacker.test/frame"></iframe>
        <object data="https://attacker.test/object"></object>
        <a href="javascript:run()"><text>link</text></a>
        <image href="https://attacker.test/image.svg" />
        <use xlink:href="https://attacker.test/sprite.svg#icon" />
        <style>text { fill: url(https://attacker.test/style.svg#paint) }</style>
        <text href="javascript:run()" xlink:href="https://attacker.test/xlink" style="fill:url(https://attacker.test/paint)">visible diagram</text>
        <path d="M0 0 L1 1" />
      </svg>
    `
    mermaidMock.render.mockResolvedValueOnce({ svg: hostileSvg, bindFunctions: mermaidMock.bindFunctions })
    const { container } = render(<MarkdownContent content={'```mermaid\ngraph TD\n  A --> B\n```'} />)

    await waitFor(() => expect(container.querySelector('[role="img"] svg path')?.getAttribute('d')).toBe('M0 0 L1 1'))

    expect(container.querySelector('[role="img"]')).toHaveClass('newshub-mermaid')
    const svg = container.querySelector('[role="img"] svg')
    expect(svg).not.toBeNull()
    const forbiddenTags = new Set(['foreignobject', 'script', 'iframe', 'object', 'embed', 'style', 'a', 'image', 'use', 'img'])
    for (const element of [svg, ...svg.querySelectorAll('*')]) {
      expect(forbiddenTags.has(element.localName.toLowerCase())).toBe(false)
      for (const attribute of element.attributes) {
        const name = attribute.name.toLowerCase()
        expect(name.startsWith('on')).toBe(false)
        expect(['href', 'xlink:href', 'style']).not.toContain(name)
      }
    }
    expect(mermaidMock.bindFunctions).not.toHaveBeenCalled()
  })

  it('normalizes dimensions from a valid numeric viewBox after sanitization', async () => {
    mermaidMock.render.mockResolvedValueOnce({
      svg: '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-10 2.5e2 320.5 119.25" width="100%" height="100%"><text style="fill:red">diagram</text></svg>',
    })
    const { container } = render(<MarkdownContent content={'```mermaid\ngraph TD\n  A --> B\n```'} />)

    await waitFor(() => expect(container.querySelector('.newshub-mermaid svg')?.getAttribute('width')).toBe('321'))

    const svg = container.querySelector('.newshub-mermaid svg')
    expect(svg?.getAttribute('height')).toBe('120')
    expect(svg?.getAttribute('viewBox')).toBe('-10 2.5e2 320.5 119.25')
    expect(svg?.querySelector('text')?.hasAttribute('style')).toBe(false)
  })

  it.each([
    ['non-numeric width', '0 0 NaN 120'],
    ['infinite width', '0 0 Infinity 120'],
    ['negative width', '0 0 -1 120'],
    ['zero width', '0 0 0 120'],
    ['width above limit', '0 0 10001 120'],
    ['non-finite exponent', '0 0 1e999 120'],
    ['zero height', '0 0 320 0'],
    ['height above limit', '0 0 320 10001'],
    ['malformed number', '0 0 320px 120'],
    ['wrong number count', '0 0 320'],
    ['repeated separator', '0,,0 320 120'],
    ['missing viewBox', null],
  ])('leaves original dimensions unchanged for %s viewBox', async (_description, viewBox) => {
    const viewBoxAttribute = viewBox === null ? '' : ` viewBox="${viewBox}"`
    mermaidMock.render.mockResolvedValueOnce({
      svg: `<svg xmlns="http://www.w3.org/2000/svg"${viewBoxAttribute} width="100%" height="100%" onload="run()"><text style="fill:red">diagram</text></svg>`,
    })
    const { container } = render(<MarkdownContent content={'```mermaid\ngraph TD\n  A --> B\n```'} />)

    await waitFor(() => expect(container.querySelector('.newshub-mermaid svg text')?.textContent).toBe('diagram'))

    const svg = container.querySelector('.newshub-mermaid svg')
    expect(svg?.getAttribute('width')).toBe('100%')
    expect(svg?.getAttribute('height')).toBe('100%')
    expect(svg?.hasAttribute('onload')).toBe(false)
    expect(svg?.querySelector('text')?.hasAttribute('style')).toBe(false)
  })

  it('uses a strict directive-protected configuration and never binds generated functions', async () => {
    const bindFunctions = vi.fn()
    mermaidMock.render.mockResolvedValueOnce({ svg: SAFE_SVG, bindFunctions })
    const source = [
      '%%{init: {"securityLevel":"loose","startOnLoad":true,"maxTextSize":999999,"maxEdges":999999,"htmlLabels":true,"flowchart":{"htmlLabels":true},"themeCSS":"body{}","themeVariables":{"primaryColor":"red"},"secure":[]}}%%',
      'graph TD',
      '  A --> B',
    ].join('\n')
    const { container } = render(<MarkdownContent content={`\`\`\`mermaid\n${source}\n\`\`\``} />)

    await waitFor(() => {
      expect(mermaidMock.render).toHaveBeenCalledTimes(1)
      expect(container.querySelector('[role="img"] svg text')?.textContent).toBe('diagram')
    })
    expect(container.querySelector('[role="img"]')).toHaveClass('newshub-mermaid')
    const config = mermaidMock.initialize.mock.calls.at(-1)?.[0]
    expect(config).toMatchObject({
      securityLevel: 'strict',
      startOnLoad: false,
      maxTextSize: 20_000,
      maxEdges: 500,
      htmlLabels: false,
      flowchart: { htmlLabels: false },
    })
    expect(config.secure).toEqual(expect.arrayContaining([
      'securityLevel',
      'startOnLoad',
      'maxTextSize',
      'maxEdges',
      'htmlLabels',
      'flowchart',
      'themeCSS',
      'themeVariables',
      'secure',
    ]))
    expect(mermaidMock.render.mock.calls[0][1]).toContain('"securityLevel":"loose"')
    expect(bindFunctions).not.toHaveBeenCalled()
  })

  it('does not render input over the 20,000-character limit and displays it as text', () => {
    const oversized = `<img src=x onerror=run()>${'a'.repeat(20_001)}`
    const { container } = render(<MarkdownContent content={`\`\`\`mermaid\n${oversized}\n\`\`\``} />)

    expect(screen.getByRole('alert')).toHaveTextContent('超过安全长度限制')
    expect(screen.getByRole('alert').querySelector('pre')?.textContent).toBe(oversized)
    expect(container.querySelector('img')).toBeNull()
    expect(mermaidMock.initialize).not.toHaveBeenCalled()
    expect(mermaidMock.render).not.toHaveBeenCalled()
  })

  it('ignores a resolved render after the source changes', async () => {
    let resolveFirstRender
    mermaidMock.render.mockImplementationOnce(() => new Promise((resolve) => {
      resolveFirstRender = resolve
    }))
    const { container, rerender } = render(<MarkdownContent content={'```mermaid\ngraph TD\n  A --> B\n```'} />)

    await waitFor(() => expect(mermaidMock.render).toHaveBeenCalledTimes(1))
    rerender(<MarkdownContent content={'```mermaid\ngraph TD\n  C --> D\n```'} />)
    await waitFor(() => expect(mermaidMock.render).toHaveBeenCalledTimes(2))

    await act(async () => {
      resolveFirstRender?.({ svg: '<svg><text>stale diagram</text></svg>' })
    })
    expect(container.textContent).not.toContain('stale diagram')
    await waitFor(() => expect(container.querySelector('[role="img"] svg text')?.textContent).toBe('diagram'))
  })
})
