import { startMocking } from './browser.ts'

async function bootstrap() {
  // No component/provider can request API data before the worker is ready.
  await startMocking()
  const badge = document.createElement('aside')
  badge.id = 'newshub-mock-status'
  badge.setAttribute('aria-label', '模拟接口环境')
  badge.textContent = `MOCK · ${window.__NEWSHUB_MOCK__?.scenario} · 合成数据；修改 scenario 参数并刷新以重置`
  badge.style.cssText = 'position:fixed;bottom:0;left:0;right:0;z-index:2147483647;padding:6px 12px;background:#173c31;color:#fff;font:12px/1.5 monospace;pointer-events:none'
  document.body.append(badge)
  await import('../main.jsx')
}
void bootstrap().catch(() => {
  // Do not echo raw exception messages: they can contain URLs or response details.
  const message = document.createElement('p')
  message.setAttribute('role', 'alert')
  message.textContent = '模拟环境启动失败。检查 scenario 名称、MSW 依赖和 Service Worker 支持；应用未启动，也未连接真实 API。'
  document.getElementById('root')?.replaceChildren(message)
})
