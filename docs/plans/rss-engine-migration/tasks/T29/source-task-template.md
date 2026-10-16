# T29 单来源执行工单的实例化合同

此文件是模板，尚无真实source_id，不是可执行工单。T24必须对实际库中每个source_id建立独立 `tasks/T29-<source_id>/task.md`、`tests.md`、`report.md`，并更新TASKS/DAG/总数；不能在T29汇总PR中批量改源。未知数据只能BLOCKED。

task.md必填：实际source_id/legacy key/Source PK；旧选择规则；新Feed或已验证路由及实际条目；正文mode/policy/content_kind；实例account绑定；目标owner/expected epoch；覆盖差异；保留PK/FK/hash清单；批准的停更或切换决定；来源窗口/执行人/批准文件；当前及目标SHA/digest/manifest；备份恢复点/兼容SHA；独占source-cutover锁；前置T28及来源必要的T00/T01/T18验收。

tests.md必填：切换前计数/PK/FK/hash；暂停和排空旧任务；epoch晚写拒绝；后台新条目/首访本地阅读；A/B/匿名隔离；旧译文/收藏/研究/组/ReadingDay保留；原选择覆盖差异人工验收；失败暂停/兼容回滚实测；该源精确命令参数及预期结果。不能以全站平均成功率替代单源结果。

report.md必填：上述每项真实结果、开始结束时刻、批准引用、执行/审核Agent、source_id和epoch、SHA/PR/CI、工件hash、未决问题、副作用/回滚。缺授权/Feed/网关/凭据/测试条件即BLOCKED，未运行标NOT_RUN；只有全部通过才DONE。

执行命令由C11固定的rss_migration plan/apply/verify生成，apply只接受已批准参数，非API/直接SQL绕过。工单按全局锁顺序执行。旧系统从未支持的新Feed回滚仅paused；既有不支持来源须明确批准history_only。全部工单DONE后，T29方能通过并解除T30阻塞。
