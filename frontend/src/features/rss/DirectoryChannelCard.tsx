import { Check, Clock3, FileText, Plus, Rss } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { CSSProperties } from 'react'
import './directoryChannelCard.css'

export interface DirectoryEntry {
  id: string
  name: string
  description: string
  kind: string
  public_url: string
  executable: boolean
  subscribed: boolean
  recommended?: boolean
  tags?: string[]
  cached_articles: { id: number; title: string; publish_time?: string | null }[]
}

const articleDate = new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric' })

function formatArticleDate(value?: string | null) {
  if (!value) return null
  const date = new Date(value)
  return Number.isFinite(date.getTime()) ? articleDate.format(date) : null
}

function channelIdentity(entry: DirectoryEntry) {
  let host = ''
  try { host = new URL(entry.public_url).hostname.replace(/^www\./, '') } catch { /* Route templates have no host. */ }
  const hue = Array.from(host || entry.name).reduce((hash, character) => (hash * 31 + character.codePointAt(0)!) % 360, 0)
  return { host, hue, initial: Array.from(entry.name.trim())[0]?.toUpperCase() || 'R' }
}

export default function DirectoryChannelCard({ entry, selected, disabled, onSelect }: {
  entry: DirectoryEntry
  selected: boolean
  disabled: boolean
  onSelect: () => void
}) {
  const { host, hue, initial } = channelIdentity(entry)
  const articles = entry.cached_articles
  return <article className={`rss-directory-card${selected ? ' is-selected' : ''}`} style={{ '--channel-hue': hue } as CSSProperties}>
    <header className="rss-directory-card-heading">
      <span className="rss-directory-card-mark" aria-hidden="true">{initial}<Rss size={12} /></span>
      <div className="rss-directory-card-identity">
        <h3>{entry.name}{entry.recommended && <span className="rss-directory-featured">目录精选</span>}</h3>
        <p className="rss-directory-card-address" title={entry.public_url}>{entry.public_url}</p>
      </div>
    </header>
    {entry.description.trim() && <p className="rss-directory-card-description">{entry.description}</p>}
    {!!entry.tags?.length && <ul className="rss-directory-card-tags" aria-label="频道分类">
      {entry.tags.map(tag => <li key={tag}>{tag}</li>)}
    </ul>}
    {articles.length > 0 && <section className="rss-directory-card-preview" aria-label={`${entry.name}近期文章`}>
      <p className="rss-directory-card-section-title"><FileText size={13} aria-hidden="true" />近期文章<span>{articles.length} 条预览</span></p>
      <div className="rss-directory-card-stories">
        {articles.map(article => {
          const date = formatArticleDate(article.publish_time)
          return <Link className="rss-directory-card-story" key={article.id} to={`/news/${article.id}`}>
            <span className="rss-directory-card-story-art" aria-hidden="true">{Array.from(article.title.trim())[0] || <FileText size={24} />}</span>
            <strong>{article.title}</strong>
            {date && <time dateTime={article.publish_time!} title="已有文章记录中的时间"><Clock3 size={11} aria-hidden="true" />{date}</time>}
          </Link>
        })}
      </div>
    </section>}
    <footer className="rss-directory-card-footer">
      <span className="rss-directory-card-source"><Rss size={13} aria-hidden="true" />{host || 'RSS 频道'}</span>
      <button type="button" className={`workspace-button${selected ? '' : ' secondary'}`} disabled={disabled || !entry.executable || entry.subscribed}
        aria-pressed={selected} aria-label={`${selected ? '已选择' : '选择订阅'} ${entry.name}`} onClick={onSelect}>
        {selected ? <Check size={14} aria-hidden="true" /> : <Plus size={14} aria-hidden="true" />}
        {selected ? '已选择' : entry.executable ? '选择订阅' : '暂不可订阅'}
      </button>
    </footer>
  </article>
}
