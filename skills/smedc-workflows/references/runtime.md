# 运行、恢复和原生工具桥

## 启动与保存

`native-adapters.js` 是一个无依赖函数表达式，可在提供实际 `tools` 的宿主 JavaScript 执行环境中求值得到工厂。它直接调用已发现的官方 MCP、Codex 与 Gmail 工具，没有 HTTP、凭据或替代 MCP 客户端。首版只绑定核心已验证的 canonical smedc 入口：officialBinding={entryName:smedc,namespace:mcp__smedc__,serviceOrigin:官方origin}。由核心安装／登录核实后传入，不来自企业配置；其他命名空间、缺失绑定或跨服务器同名后缀一律拒绝，不猜第一个匹配。

先通过本地文件工具读取安装锁哈希已核对的完整脚本；例如 Codex functions.exec 以安全单引号转义的 adapterPath 调用 exec_command 读取，max_output_tokens 设30000，检查退出码及无截断后 store('workflowAdapterSource',result.output)，只输出加载字节数。不要将模块全文打印到聊天。下一次调用：

```javascript
const native = (0, eval)(load("workflowAdapterSource"))(tools, {
  localScript: "/absolute/installed/skill/scripts/workflow.py",
  saveOutcome, // 下方同样使用真实原子保存的逐动作日志回调
});
```

此示例中的绝对路径由实际安装位置解析。不要将任意网页、配置或品牌文字当代码求值。`localScript` 用于原生任务 TOML 精确读回；真实调用 tools.exec_command，不是静态声明。每次执行环境重置后重新加载工厂；不能复用旧浏览器句柄。

实际初始化时，先解析安装路径和本轮规范目录，再建立真实原子持久化回调：

```javascript
let native;
const saveOutcome = (event) =>
  native.saveLocal(
    runDir + "/operation-journal/" + event.operationId + ".json",
    event,
  );
native = (0, eval)(load("workflowAdapterSource"))(tools, {
  localScript: scriptPath,
  saveOutcome,
});
const save = (value) => native.saveLocal(statePath, value);
```

saveLocal 直接调用真实 exec_command 和包内 save-chunk CLI，按有界片段写入、哈希核验、fsync 和原子替换；重复片段核对后复用。它不受 shell 单参数大小限制，也不会打印完整状态。save 必须完成后才继续，不能只存宿主内存。runDir/statePath 都必须在本机专属工作区，不来自中央业务文字。

pythonExecutable 先从实际 load_workspace_dependencies 取得并检查版本，不假定新 Mac 的系统 Python 可用；下面 python3 命令均指已验证解释器。

本地 CLI 都接受 `--input INPUT_JSON` 或 `--json JSON`；写大迁移包时使用 `--output` 将完整结果落盘，仅回传计数摘要。不要把所有回执／正文加载到聊天。

长操作必须 `native.withLease(session,meta,()=>actualTool(args),saveOutcome)`；这是等待真实工具期间每30秒并发续租的实现。saveOutcome 为逐动作本机持久日志回调（开始记录和结果都要写），可用同一 `workflow.py save`，保存 startedAt/endedAt 及原结果，不仅内存保存。Gmail send/readback 内部也使用它。续租失败不声称撤回已经派发的请求：保留实际结果为 unknown，后续 check 拒绝新动作，恢复原轮后先核对。

评价预设的完整审计与独立业务／证据处置读 [review execution policy](review-execution-policy.md)，用真实工具包装器保留经凭据脱敏的原错误；withLease 不代替完整调用审计。

## 单轮约束

### 浏览器来源读取

美团页面读取、查询、只读导出及原件下载属于来源采集；浏览器选择遵循 [浏览器选择与恢复](browser.md)。它们不对应中央动作意图类型。先从冻结 snapshot 取得准确来源账号、门店／POI、渠道和窗口；每个范围前读取当前配置和权限，应用本轮已收缩的范围，并通过 `manage_workflow_run` 的 `renew` 检查当前控制、指定安装和租约，再执行该范围的浏览器调用并保存开始／结束审计及真实结果。长操作用 `native.withLease`；浏览器接口不能放入同一工具回调时，将操作拆成有界调用、在调用边界续租，接续原导出／下载，不重建正在进行的请求。

`review_collect` / `review_export` 不是官方动作类型；采集前不构造它们，也不借用 `review_sync` 或伪造 `observedFactsHash`。采集完成、拟同步事实已保存后才生成真正的 `review_sync` 意图。来源读取／导出成功只证明取得原件，不证明同步、上传、发布或邮件成功；生成导出文件也不改变订单、收货或评价业务状态。

### 中央动作与收尾

1. 读取当前官方身份、工作流／控制／指定安装。权限失败或配置不可读就停止本工作流新外部动作，不读取待上传原件。按 `workflow.py lock` 原子取得本机锁；既有锁不能因年龄被抢走。
2. `workflow.py window` 输入 workflowType 和带时区 now：每日是前一完整营业日；评价是前一日＋当天；周报为上一自然周。存在未完成轮则传 resume 原窗口，跨午夜保持原日期。漏跑提示基于中央状态／已保存宿主计划，历史补数必须先取得明确范围和服务 prepare_backfill 预览，不自动扩大到数月。
3. `native.openRun` 重新取当前配置后 start 或 resume，服务返回不可变 snapshot、runId、leaseExpiresAt 和续期间隔。原子保存完整 binding、snapshot、窗口、包版本和检查点。普通配置更新从下一轮生效，当前轮不混入新门店或邮箱。暂停后恢复或明确接管后，openRun 保留原 runId，重新读取当前指定安装、assignmentEpoch 和 controlVersion 交由服务验证；不复用旧绑定，也不另建新日期轮。移除门店、渠道、数据能力、收件人或发件人、停用发布／邮件及新增忽略身份属于即时收缩；服务累计限制未完成轮，再扩大设置也不会恢复该轮已撤回的范围。
4. 中央支持的动作是上传 `upload`、SMEDC 数据下载 `download`、评价同步 `review_sync`、回复发布 `review_publish` 和邮件 `email`。这些动作前调用 `native.claim(session,intent)`：renew、check_actions、持久 intent；仅 permitted=true 可执行新动作。即便已保存 intent，真正发起前再 `native.check` 核对停用、授权、epoch、租约与业务权限。长阶段按服务 renewAfterSeconds 续期，失败停止新动作。浏览器来源读取按上一节执行，不要求不存在的采集动作契约。
5. 原业务技能执行来源读取／导出、上传、评价与报告阶段。每一范围边界落盘，保留导出任务 ID 和来源完整筛选；故障只阻塞相关数据类／来源／邮件阶段。浏览器超时先读回原导出任务，不重复创建。
6. 动作结果独立记录：accepted/queued/processing 不是完成；上传必须 published/applied，评价须核对准确来源身份及真实完整商家回复，邮件须已发送原件读回。`native.record` 只提交匹配 intent 的有限回执；外部请求结果不明记 unknown。正文或 artifact 重生成不换去重身份，通知按每评价×收件人保留声明，不能靠重分批次绕过去重。
7. 已有 intent/unknown/confirmed 的 claim 返回不可重放。先按 action 状态和原 provider 标记／jobId 核对，确认成功才记录；未找到邮件不是未发送证明。明确未执行的失败才允许同一逻辑动作重试。需人工核对的旧项保留，不以本轮成功清空。
8. 完成时 record_summary / `native.closeRun`，真实结果区分 succeeded、partial、needs_attention、failed、unknown；不把独立阶段成功说成整轮成功。报告和原件按下方规则处理；最后释放本机锁。中断保留锁和精确续跑依据，先核对旧轮状态再恢复，不并行开启第二轮。

## 回执、清理和归档

中央不得保存报告全文、客户原评／回复、邮件正文、原 XLSX、聊天或完整网页。中央只存身份、状态、摘要、哈希及必要 provider/job 回执；详细证据和最终报告留本机。

`native.cleanupProof(session,actionIds)` 实时读取当前中央未解决动作并分批 get 精确回执，只有当前轮全部指定动作 confirmed 才返回 30 秒有效的证明。保存到 run 外的精确证据路径，所有文件 hash/owner 验证通过才清理；过期刷新。`workflow.py cleanup` 只删明确列举、run 内、未改变且有中央 confirmed 回执的原件；输入包含 runRoot/runId/workflowId/lockOwnerPath/centralProof/files/resultPath，每文件为 path/sha256/actionId。resultPath 必须持久保存逐文件清理结果，不能列入删除名单；中途失败仍保留准确 deleted/retained。不得传家目录、共享目录或最终报告；保留失败／unknown／冲突证据。

评价继续使用原 `review_run.py archive/manifest/cleanup` 的全部七项整轮成功门槛、锁归属、归档证据和逐文件哈希。新工作流 run.json 含 workflowBinding，cleanup gate 须额外提供中央证明路径／哈希及本轮全部 action ID。中央证明不会替代旧门槛。七项门槛未通过时保留需要恢复的本地文件。

### 临时文件清理

1. 新文件在采集或生成时按 [每日](execution.md#每日原件留存)、[评价](execution.md#评价原件留存) 或 [周报](execution.md#周报文件留存) 的规则分流。本轮可丢弃文件放进 `runRoot/temporary/`，逐项登记绝对路径和 SHA-256 至 temporary 外的本轮 `temporary-manifest.json`。原件、文件夹和报告的归属以实际工具返回及本轮登记为准。保留内容放在 temporary 外，执行进度只引用长期保留且已经核对的证据。
2. 核验各业务的清理条件，完成原执行计划，再执行 `native.closeRun`。关轮后使用 `native.finishedCleanupProof(session)` 核对中央已结束、succeeded 且无本轮未解决动作，获取 30 秒有效的确认。partial、failed、unknown 或证据不足时保留临时文件，记录原因。此步骤使用完成轮的读取接口，无需续租或重开。
3. 持本轮本机锁，将 `{runRoot,runId,workflowId,lockOwnerPath,centralProof,files}` 交给 `workflow.py cleanup-temporary --input INPUT`，其中 files 是关轮前确认仍存在的已登记项 `[{path,sha256}]`，保存为固定清理清单以便接续。脚本核对中央确认、归属、路径、摘要和进度引用，逐项删除并更新 `runRoot/temporary-cleanup-result.json`。成功后可移除本轮登记的空临时目录。中断后用原清单和新的中央读回接续本地清理，沿用同一轮 ID 并核对本地锁。清理失败不重放已完成的外部动作。

可选聊天归档仅完全成功后使用原生 set_thread_archived；失败保留提示，不删除聊天文件或重跑业务。失败仍有宿主可见反馈，即使 Gmail 不可用。

范围下载完成后，用 `workflow.py download-proof` 读取官方 launcher 返回的 localDirectory/manifest.json 与全部准确文件，核对 dataset、范围、准确门店、文件数、字节数和逐文件 checksum。输入 response、原 intent、claim 返回 identityHash、已验证运行 launcherVersion；可选 bundle requestId。输出 evidence=launcher_transfer 的回执，通过 native.record 提交。只有包装成功而无实际本地文件不能确认；默认 range 不需要服务器下载 jobId 或预先知道 manifestHash。不要改为 manual_resolution。若范围候选返回相似但未选择门店，保留并停止该动作，缩小官方选择／精确 storeId；不声称其属于冻结范围。

评价同步先把本轮唯一完整身份、拟提交 payload、原 existingId 和需保持的 independentRows 保存为 plan.entries；每项带原始解析记录的 sourceIdentity。用 `review-sync-intent` 生成 source/storeNames/window 范围和 observedFactsHash，再 claim/check，实际 `upsert_store_reviews` 放在 withLease 的 external_write 中。所有 `query_store_reviews` 页结果逐份保存后，`native.confirmReviewSync(session,intent,claim,{planPath,readbackPaths,proofInputPath})` 调用真实本地完整字段比较，再提交 smedc_readback；recordIds 为服务返回的 id，不能用 feedbackId。receipt 含同一 identityHash/observedFactsHash/resultHash、匹配数量与 observedAt，没有客户正文，不需要 manual_resolution 或正常运行人工确认。

`native.confirmDownload` 同样调用真实 download-proof：传实际 response、已验证 launcherVersion、可选 requestId 和专属 proofInputPath。本地验证纯事实可在现有动作暂停／租约丢失后核对，但先 get 原动作元数据，不能借此派发新业务操作；服务仍验证当前角色、内容权限及原／现行安装绑定。传输未知时保留原目录与会话，先核对已有本地结果；只读分区的新安全读取可以使用新的读取动作 ID，不给发信／发布绕过去重。
