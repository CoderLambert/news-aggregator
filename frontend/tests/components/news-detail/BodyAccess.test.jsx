import { render, screen, fireEvent } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import FullContentFetchStatus from '@/components/news-detail/FullContentFetchStatus'
import { hasReadableFullContent } from '@/types/news'

it('only permits restricted body rendering with server-granted access', () => {
  const news = { reading_policy: 'rss_summary_only', full_content: 'Saved body', full_content_state: 'complete', has_full_content: true }
  expect(hasReadableFullContent(news)).toBe(false)
  expect(hasReadableFullContent({ ...news, body_access_granted: true })).toBe(true)
})

it('offers an explicit attempt for previously unsupported articles when allowed', () => {
  const onFetch = vi.fn()
  render(<FullContentFetchStatus news={{reading_policy:'rss_summary_only',body_access_granted:true,can_fetch_full_content:true,full_content_fetch_status:'unsupported'}} onFetch={onFetch} />)
  fireEvent.click(screen.getByRole('button', {name:'尝试获取正文'}))
  expect(onFetch).toHaveBeenCalledOnce()
})

it('still hides the attempt when source fetching is unavailable', () => {
  render(<FullContentFetchStatus news={{reading_policy:'rss_summary_only',body_access_granted:true,can_fetch_full_content:false,full_content_fetch_status:'unsupported'}} onFetch={vi.fn()} />)
  expect(screen.queryByRole('button',{name:'尝试获取正文'})).not.toBeInTheDocument()
})
