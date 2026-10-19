# Test T08 · 译文详情、问答与朗读同源

> 当前状态：修复候选待新 HEAD CI；以下历史快检只针对 88ea7fc8889150ec0cc5db5b83a513f0150bca86，不代表后续代码通过。

对应冻结契约：docs/features/byok/tasks/T08-translation-readers.md 与冻结 Test 契约（ed58afa7a72ae905e2a2ffc315d968ca3634b8f2）。

| 用例 | 候选覆盖 | 状态 |
| --- | --- | --- |
| T08-01 | Django detail/chat/TTS 同一 owner result，读路径不派发 provider | NOT_RUN |
| T08-02 | 同篇文章 A/B 各自的 result 与音频 cache variant 隔离 | NOT_RUN |
| T08-03 | 原文更新后显式读取旧 result，显示 stale 并保留旧 source title | NOT_RUN |
| T08-04 | 无当前个人结果时使用 shared/current fallback，不让 stale 私有结果覆盖 | NOT_RUN |
| T08-05 | 软删除连接后读取自己的完成历史；跨用户/未知 result fail closed | NOT_RUN |
| T08-06 | detail 标记 current 时同时核对冻结文章 ID、正文哈希、标题与 revision | NOT_RUN |
| T08-07 | chat 历史/回放精确绑定 evidence；legacy 原文历史仅在原文模式可见 | NOT_RUN |
| UI-01 | 详情选择器切换精确保存结果并标注 stale source | NOT_RUN |
| UI-02 | 聊天请求和语音请求传递精确 result ID；播放器切换账户会清除音频与 resume state | NOT_RUN |

主要测试文件：
- backend/api/tests/test_ai_private_translation_t05.py
- frontend/tests/components/news-detail/PrivateTranslationReaders.test.tsx
- frontend/tests/components/NewsChatAssistant.test.jsx
- frontend/tests/services/chatStream.byok.test.jsx
- frontend/tests/context/speechPlayer.test.jsx

历史快检证据（不覆盖 T08 专项测试）：
- HEAD：88ea7fc8889150ec0cc5db5b83a513f0150bca86；workflow run 39249667481，2026-10-19 UTC。
- changes 成功；dev-backend 成功（快速语法、安全回归、CI 合同检查，不是 T08 Django 测试套件）。
- dev-frontend 的类型检查成功、快速 lint 失败：NewsDetail.tsx 中手动 memoization 依赖缺失/回调不稳定；该候选未进入完整门禁。
- backend-and-release-gates、frontend、merge-gate 均跳过。因此 T08-01 至 T08-05 和 UI-01/02 均未验证；本次修复 HEAD 的适用测试与完整 CI 待跑。
- SDK_LOCAL / PROXY_LOCAL / PROVIDER_REAL / 浏览器 UAT：NOT_RUN。使用合成内容，不发起真实付费 provider 请求，也不触碰生产。
- GET/detail/chat-context/TTS resolver 只解析已保存结果，不派发翻译任务。
- 独立 reviewer 与适用完整 CI 通过前，PR 保持 Draft。
