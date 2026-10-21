import { Streamdown } from 'streamdown'
import type { Components } from 'streamdown'

const animation = { animation: 'fadeIn', duration: 180, easing: 'ease-out' } as const
const components: Components = {
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
}

/** Render accumulated snapshots without treating incomplete Markdown as a final result. */
export default function StreamingMarkdown({ content }: { content: string }) {
  return (
    <Streamdown
      className="article-markdown prose prose-gray mx-auto w-full max-w-[86ch] overflow-hidden"
      mode="streaming"
      isAnimating
      animated={animation}
      components={components}
      skipHtml
      controls={false}
    >
      {content}
    </Streamdown>
  )
}
