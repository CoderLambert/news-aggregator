import { useState, useEffect } from 'react'
import { useParams, Link } from 'react-router-dom'
import { fetchNewsDetail } from '../services/api'
import LoadingSpinner from '../components/LoadingSpinner'
import NodeRenderer from 'markstream-react'
import 'markstream-react/index.css'

export default function NewsDetail() {
  const { id } = useParams()
  const [news, setNews] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchNewsDetail(id)
      .then(data => setNews(data))
      .catch(err => console.error(err))
      .finally(() => setLoading(false))
  }, [id])

  if (loading) return <LoadingSpinner />
  if (!news) return (
    <div className="text-center py-20 text-gray-400">
      <p>新闻未找到</p>
      <Link to="/" className="text-blue-600 mt-2 inline-block">返回首页</Link>
    </div>
  )

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <Link to="/" className="text-sm text-blue-600 hover:underline mb-6 inline-block">
        &larr; 返回列表
      </Link>

      <article>
        <header className="mb-6">
          <span className="inline-block bg-blue-50 text-blue-600 text-xs px-2 py-1 rounded mb-3">
            {news.category_name}
          </span>
          <h1 className="text-2xl md:text-3xl font-bold text-gray-900 leading-tight mb-4">
            {news.title}
          </h1>
          <div className="flex flex-wrap items-center gap-3 text-sm text-gray-500">
            {news.author && <span>作者: {news.author}</span>}
            <span>来源: {news.source_name}</span>
            <span>{new Date(news.publish_time).toLocaleString('zh-CN')}</span>
          </div>
        </header>

        {news.cover_image && (
          <img
            src={news.cover_image}
            alt={news.title}
            className="w-full rounded-xl mb-6"
          />
        )}

        <div className="text-gray-700 leading-relaxed">
          <NodeRenderer
            content={news.content || ''}
            codeBlockProps={{
              showHeader: true,
              showCopyButton: true,
              showCollapseButton: false,
              showFontSizeButtons: false,
              showTooltips: true,
            }}
            codeBlockThemes={{
              themes: ['vitesse-dark', 'vitesse-light'],
              darkTheme: 'vitesse-dark',
              lightTheme: 'vitesse-light',
              monacoOptions: {
                fontSize: 14,
                fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Source Code Pro', Menlo, Consolas, monospace",
                padding: { top: 12, bottom: 12 },
                lineNumbers: 'on',
                wordWrap: 'on',
                minimap: { enabled: false },
                scrollbar: { vertical: 'hidden', horizontal: 'hidden' },
                scrollBeyondLastLine: false,
                overviewRulerLanes: 0,
                hideCursorInOverviewRuler: true,
                renderLineHighlight: 'none',
                renderLineHighlightOnlyWhenFocus: true,
                contextmenu: false,
                readOnly: true,
                domReadOnly: true,
                mouseWheelZoom: false,
                smoothScrolling: true,
                cursorBlinking: 'blink',
                cursorSmoothCaretAnimation: 'on',
              },
            }}
          />
        </div>

        <div className="mt-8 pt-6 border-t border-gray-200">
          <a
            href={news.url}
            target="_blank"
            rel="noreferrer"
            className="text-blue-600 hover:underline text-sm"
          >
            阅读原文 &rarr;
          </a>
        </div>
      </article>
    </div>
  )
}
