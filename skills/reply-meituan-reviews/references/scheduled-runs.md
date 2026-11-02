# 有状态的独立定时运行

仅在调用方已配置周期任务时读取。这里优化执行方式，不授予发布、邮件、同步或删除权限；业务范围、授权及清理门槛以该任务保存的现行策略为准。真实企业、门店、邮箱、POI及业务内容放调用项目，不放技能。

## 轻量启动与恢复

- 独立轮次只读现行策略、紧凑 `state.json`、持久通知台账、忽略标记及仍未解决的具体事项。不扫描旧聊天、全部历史报告或旧版 memory。历史成功批次不重放；已清理文件缺失不算失败。
- 每轮先取得任务原子锁；旧锁未确认结束不抢锁。固定本轮开始日期及唯一 runId，保持既有查询范围。新取浏览器/标签/iframe句柄；不使用上轮 REPL 的旧 R、闭包、ref 或内存变量。浏览器能力文档仍先读。
- 每个门店×渠道完成查询后，立即原子持久化筛选、来源全名/POI、日期、总数及已生成导出任务的标识/时间；用下方 `checkpoint`，不要等整批结束再写。单次浏览器调用只处理一个渠道范围，预算小于20秒；读到加载中就落盘当前阶段并结束该调用，下一调用继续有界等待，不把等待包装成长循环。
- 发生超时/运行时重置：读本轮检查点与现有导出任务，只恢复未完成范围。先核对已提交任务，不重复导出、回复、通知或upsert。将完整错误写入本轮 errors.json，含阶段/来源身份/调用时间/原始工具错误；不得丢弃 isError、只留“失败”或把 Promise.all 的拒绝误当其余请求未执行。

## 固定本地处理

复用 `scripts/review_run.py` 和 `scripts/review_workbook.mjs`，执行而非全文读入或每轮改写。运行时用 `load_workspace_dependencies` 返回的 Python/Node及库；在项目共享工具目录（不在run内）按SHA同步原版MJS为 `build.mjs`，仅首次或源版本变化时复制；在该目录链接 `node_modules` 到返回的依赖目录后执行，不修改脚本或依赖目录。共享构建器和依赖链接不进本轮清理清单。不能把任务企业、门店、文件名或轮次硬编码到脚本。

1. 本轮 `run.json` 至少含 `runId/startedAt/startDate/endDate`；`task.json` 含 `enterpriseName/mappings/replyWhitelist/ignoredRecords`。映射格式与主技能相同；忽略项为 `poiId/source/feedbackId`。
2. 每份已明确归属的原导出登记到 `exports.json` 数组：`path/poiId/source/sourceStoreName/storeName/snapshotAt/pageCount`。只登记本轮实际文件，不用 Downloads 通配搜索猜归属。来源时间与生成任务关联仍按导出参考核验。逐份文件读取器验证完整行数及字段；页面兜底沿用同一 records 格式并单独对账。
3. `python review_run.py parse --run-dir RUN --task TASK` 生成 records.json、来源文件摘要。页面兜底按主技能省略客户原评中不可识别的 emoji／图形，省略说明单独记录，不加入 `issues`，不以旧的 `contentHasUnlabelledImages` 标记跳过起草或同步；省略后为空则按无正文处理。需补读的其他问题行仍保留，`issues` 非空时仅对该行核验、修正；不因一行异常丢弃其余有效行，不直接同步有问题行。白名单新稿由模型按文案技能生成，写 `draftReply`，核验后设 `sheetStatus=新生成待审核`；`merchantReply` 只装真实已发布回复。
4. `node review_workbook.mjs RECORDS OUTPUT_XLSX PREVIEW_DIR` 构建九列与预览；`python review_run.py verify --records RECORDS --workbook OUTPUT_XLSX` 独立逐行重开校验。构建器使用原生 Excel 日期序列值并固定北京时间显示，导出后逐秒回读一致。按当前表格技能查看预览。仅修改发生变化的构建输入，重复生成用同一脚本。若发布后内容没有变化，要求两版本的任务可复制同一文件并核对SHA，不重复构建/渲染；发布有变化则更新真实回复/状态，构建并核验执行版。
5. `python review_run.py checkpoint --run-dir RUN --observation SCOPE_JSON` 按 `poiId/source` 保存进度；JSON须含真实观测的 `observedAt/startDate/endDate/sourceStoreName/storeName/pageCount/stage`。在采集、发布、同步等阶段边界写 `timings.json`，只记时间、结果数、错误及可计时工具耗时，不声称能从空档区分模型思考与网络。
6. 归档可用 `archive --run-dir RUN --archive-dir ARCHIVE --files FILE...`，逐项复制后重开JSON并核对SHA；文件必须是本轮普通文件且归档不在run内部。归档目录由任务指定。归档成功不自动放行清理。
7. 仅当任务的全部成功门槛已逐项满足，调用 `manifest --run-dir RUN --output MANIFEST --files FILE...` 登记本轮明确文件，再调用 `cleanup --run-dir RUN --manifest MANIFEST --gate GATE --result RESULT`。gate必须含全部为true的 `collectionComplete/identitiesVerified/publicationVerified/syncReadbackVerified/notificationsVerified/noUnresolvedErrors/archiveVerified`、当前 `lockOwnerPath`，及 `evidenceFiles` 的绝对路径与SHA256。证据只能指向run外已归档的本轮记录；语义核验仍由执行代理按任务策略完成。manifest/gate/result放必要长期记录目录，不能列入删除清单。仅删除run内部文件；run外本轮原导出/审阅表按任务原有逐项归属规则处理，不能通配删。发生变化或符号链接则保留。此工具不删除历史、共享目录、台账或锁。

## 官方MCP有界读取

保留任务要求的同步前身份/存量/新旧保护与写后逐条回读，不因优化省略核验。先做一次当前权限校验；读取按最多3个并发开始，每个结果立即保存到本轮磁盘，工具 isError 和Promise拒绝都保存完整原始错误。不一次发出全部行，不用首次拒绝就丢弃其余结果的 Promise.all；用小批 Promise.allSettled 并逐项检查。若服务明确限流，降为串行，仅恢复未成功的只读项。写入仍按当前合同和任务幂等规则执行，未知提交先回读，不能把读取重试规则用于重放写入。

只把计数/差异/异常身份送回模型，完整正文、快照、回执放本轮文件；发布目标核验与文本自检仍读取所需完整正文。若合同支持一页覆盖多条的精确筛选，可减少读取次数，但必须保留来源身份唯一性与全字段对账，不能靠估计数替代逐条核验。

## 跨轮摘要

结束时原子覆盖调用方紧凑state（目标约2KB，不含客户原评/回复全文）：最近runId/范围/结果/归档路径、未解决事项的精确记录路径、持久通知/忽略标记路径。先读并保留旧轮未解决事项，新增或有证据解决后再更新，不能用“本轮成功”清空历史异常。禁止向state/memory前插整份本轮报告或连续堆叠历史摘要。完整证据留本轮归档；通知去重台账永久沿用。


企业工作流补充：task 的 sourceIdentityMappings 为中央冻结的 `{source,storeName}` 列表，export 的 sourceIdentity 为已核实的 product/accountRef/channel/sourceStoreId/sourceStoreName。不得以另一账号的同名门店匹配；原 source POI 和 channel 继续保留。run.json 的 workflowBinding 启用中央清理补充门槛，gate 中登记 centralProofPath/centralProofSha256/centralActionIds。中央证明仅补充原七项整轮门槛，不能取代 archive/lock/hash 验证。完整运行与迁移由 smedc-workflows 负责。
