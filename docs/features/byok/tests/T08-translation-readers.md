# Test T08 · 译文详情、问答与朗读同源

> 当前状态：实施候选，所有仓库测试均为 NOT_RUN；需以本 PR 精确 HEAD 的 CI 结果更新本文件。禁止将历史设计 SHA 当作代码基线。

对应冻结契约：docs/features/byok/tasks/T08-translation-readers.md 与冻结 Test 契约（ed58afa7a72ae905e2a2ffc315d968ca3634b8f2）。

| 用例 | 候选覆盖 | 状态 |
| --- | --- | --- |
| T08-01 | Django detail/chat/TTS 同一 owner result，读路径不派发 provider | NOT_RUN |
| T08-02 | 同篇文章 A/B 各自的 result 与音频 cache variant 隔离 | NOT_RUN |
| T08-03 | 原文更新后显式读取旧 result，显示 stale 并保留旧 source title | NOT_RUN |
| T08-04 | 无当前个人结果时使用 shared/current fallback，不让 stale 私有结果覆盖 | NOT_RUN |
| T08-05 | 软删除连接后读取自己的完成历史；跨用户/未知 result fail closed | NOT_RUN |
| UI-01 | 详情选择器切换精确保存结果并标注 stale source | NOT_RUN |
| UI-02 | 聊天请求和语音请求传递精确 result ID；播放器切换结果时隔离 resume identity | NOT_RUN |

主要测试文件：
- backend/api/tests/test_ai_private_translation_t05.py
- frontend/tests/components/news-detail/PrivateTranslationReaders.test.tsx
- frontend/tests/components/NewsChatAssistant.test.jsx
- frontend/tests/services/chatStream.byok.test.jsx
- frontend/tests/context/speechPlayer.test.jsx

验证边界：
- 实施基线：main ec5ae5928c9303b028bc78ad561c76f2971ea6ce（2026-10-19 UTC）。
- Candidate HEAD / 精确 CI run / 环境版本 / stdout：NOT_RUN；在有适用测试结果前不得标 PASS。
- SDK_LOCAL / PROXY_LOCAL / PROVIDER_REAL / 浏览器 UAT：NOT_RUN；本卡使用合成内容，不发起真实付费 provider 请求。
- GET/detail/chat-context/TTS resolver 均只解析已有任务结果，不会提交翻译任务。
- 独立 reviewer 与适用完整 CI 通过前，PR 保持 Draft。

