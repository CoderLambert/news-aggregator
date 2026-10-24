import { scenarios } from '../src/mocks/catalog.ts'
for (const scenario of scenarios) {
  console.log(`${scenario.id.padEnd(26)} ${scenario.label}`)
  const path = ['normal', 'news-empty', 'news-error', 'news-retry', 'news-slow', 'news-network-error',
    'news-malformed', 'news-rate-limited', 'search-race'].includes(scenario.id) ? '/' : '/news/910001'
  console.log(`  http://127.0.0.1:9530${path}?scenario=${scenario.id}`)
}
