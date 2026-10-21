# RSSD-06.1：共享发现浏览与关键词搜索界面

> 审阅：待审阅；实施：未开始；自动/人工验收：NOT_RUN。本文中的新增文件、接口、测试和命令是未来开发要求，本轮不执行。

## 目标与交付物

**目标：** 用户从完整发现页和添加弹窗获得同一精选、筛选、搜索及加载更多体验。

**交付物：** /channels/discover、共享DiscoverPanel、完整分页与URL/弹窗各自状态边界。

## 范围与前置依赖

**范围：** 浏览和搜索、IME/防抖、空错态、账号隔离、可访问性及能力关闭回退。

**不包含：** 不实现详情确认/订阅写入，不复制DTO/请求器，不将目录主题写入个人分类。

**前置依赖：** [RSSD-05](RSSD-05-可授权的频道资料与兼容发现接口.md)的已验收输出。

**必须引用的合同：** [开发合同](../../开发合同.md) C04、C05、C06、C07、C08；[完整方案](../../完整方案.md)相应产品/A编号。无需重读其他任务正文；接口以共同合同为准。

## 具体文件与输入输出

- 新增：frontend/src/features/rss/discovery/DiscoverPanel.tsx及按需FeedSearchBar/FeedFilterBar/FeedResultCard.tsx
- 新增：frontend/src/pages/RssDiscoverPage.tsx、frontend/tests/features/rss/DiscoverPanel.test.tsx
- 修改：frontend/src/features/rss/DiscoverDialog.tsx、frontend/src/pages/ChannelWorkspace.tsx、frontend/src/App.tsx；保留能力关闭时旧添加流程

**输入：** DiscoverPanel props、rssDiscoveryApi与viewer分区查询键、URL或dialog局部筛选。

**输出：** 可浏览/搜索/分页的共享面板及选中DirectoryEntry，交06.2进入详情/确认。

## 实现方案与开发步骤

**方案：** useInfiniteQuery使用完整筛选键；空输入mode=featured、关键字mode=search。page同步q/category/language/kind，dialog不改宿主URL。composition期间不请求，300ms防抖，回车即时；更词/换号清旧页与在途结果。

- [ ] 1. 确认依赖输出、当前base/head与文件所有权；按C07准备无真实.env的隔离环境，读取适用AGENTS。
- [ ] 2. 先添加下表指定负例/契约断言；运行下列自动命令，保存原行为FAIL。环境/导入错误只记BLOCKED，不作为功能负例。
- [ ] 3. 按本卡文件、输入输出和方案实现最小改动；共同接口变化先同步开发合同及消费者。
- [ ] 4. 同命令运行至目标断言PASS，再做本卡列出的受影响回归；不扩大到无关全量测试。
- [ ] 5. 完成人工验收并记录实际版本/结果；缺前提记未测。更新总览对应项及C08证据，提交仅在另获授权后进行。

## 自动测试与通过条件

| 指定用例/检查 | 必须成立的断言 |
|---|---|
| `test_page_and_dialog_share_featured_and_pagination` | 两入口同数据、首屏≤12，next_cursor触发追加且条件变化清旧页。 |
| `test_ime_debounce_enter_and_stale_response` | 组合期间0请求、300ms后1请求、回车立即，旧查询/旧viewer结果不回写。 |
| `test_url_state_and_domain_like_keyword` | 刷新/后退恢复筛选；vue.js仅本地检索，网站POST必须显式操作。 |
| `test_capability_off_preserves_old_add` | 扩展能力false/未知时新路由关闭，旧添加入口仍可操作。 |

关键断言示意（变量由该用例的隔离fixture提供，不能直接当现成测试执行）：

```typescript
expect(searchRssDirectory).not.toHaveBeenCalled()  // composition期间
expect(renderedIds).toEqual([...firstPageIds, ...secondPageIds])
```

在C07环境执行：

```bash
npm --prefix frontend run test:run -- tests/features/rss/DiscoverPanel.test.tsx tests/features/rss/DiscoverDialog.test.tsx
npm --prefix frontend run typecheck
npm --prefix frontend run lint
```

**预期：** 新增代码的目标断言先见原行为失败，实施后退出码0且断言全部通过；真实核验/基线/运营场景按本卡前提记录实际结果，不人为制造失败或把未运行记PASS。

**受影响回归与限制：** 确认services/types仍由05维护，URL发现不随输入自动触发；首次接入构建用npm --prefix frontend run build。

## 人工验收步骤

1. 用同一账号打开添加弹窗与/channels/discover，对比精选、筛选、搜索和加载更多。
2. 中文IME输入后回车、快速改词、刷新/后退，观察无半成品查询和旧结果闪回。
3. 在412px和桌面用键盘导航、Escape/焦点恢复；换号和关闭能力后确认数据隔离及旧入口可用。

每步记录PASS/FAIL/未测及候选版本；合成/隔离结果不代表生产验收。

## 完成标准与回退方式

**完成标准：** A01/A06/A07/A10/A14的浏览路径通过；两入口同一实现，组件证据与真实浏览器证据分列，后者留09。

**回退：** 关闭新能力并回到保留的旧添加界面；不清理服务端任务、用户订阅或偏好。

**交接：** 依C08给出变更文件、接口实际映射、base/head、命令/退出码、证据位置、未测和风险；不得只交“代码已写”。返回[任务总览](../../任务执行计划.md)。
