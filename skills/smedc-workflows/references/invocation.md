# 定时运行入口

安装／更新与业务运行分开。定时 prompt 明确请求创建并执行一个持久 Goal，并携带工作流绑定、固定包版本／源码修订、安装锁路径和专属 workspaceRoot。Goal 使用宿主 `get_goal/create_goal/update_goal` 生命周期；普通技能调用不自动创建 Goal。它让未完成工作能在同一聊天接续，不扩大权限，也不替代业务核验。宿主没有这些工具时，将该执行模式记为 unavailable，不创建另一个调度器。

一次调度触发是一次 invocation，对应一个任务聊天及 Goal；同一 Goal 的后续对话轮次不是新的业务运行。中央 runId、窗口、动作身份及执行队列在这些轮次间保持不变。首次触发／换机／更新时执行准备检查。每次开新轮前对照中央状态检查有效期；同一 invocation 续轮重新核对身份、控制、指定安装和浏览器来源，复用仍适用的检查。

## 启动和恢复

1. 核验安装锁和所选依赖，按 [runtime](runtime.md) 加载 native adapter。调用 `native.beginGoal({workflowId,goalRequested:true})`；只在定时 prompt 的显式 Goal 请求下传 true。同一聊天续轮复用已有 Goal，不覆盖别的 Goal。
2. 读取当前身份、配置、指定安装及当前权限。state.json 是本地缓存；缺失时用已核验安装锁、prompt 绑定和中央 installation/hostSnapshot 重建，先核对实际任务 ID、日程、模型和目录归属，不导入旧机路径。迁移回执和 unknown 动作仍从中央恢复；清空本地记录不等于清空业务历史。
3. 调用 `native.recoverRun(input)`，先查中央未结束轮或已完成窗口，再决定是否开新轮。新轮由 `native.openRun` 在 `start` 前检查中央必需项。若返回 `WORKFLOW_READINESS_REFRESH_REQUIRED`，按错误的 `capabilities` 清单和 [安装检查定义](installation.md) 实做每一项，持久保存实际结果，再传 `input.refreshChecks = async (capabilities) => /* 读取这些项目的真实检查结果数组 */` 重试。检查记录按 `capability/status/checkedAt/nextStep` 保存，时间取实际验证时刻。适配器合并仍可复用的记录、登记 `record_checks` 并核对响应，再发送 `start`；失败或未验证项目保留准确缺项，不刷新旧结果的时间。显式补跑先对同一绑定调用 `native.ensureRunReadiness(input)`，再走 `prepare_backfill`，开轮仍会复核。传旧 state 的 resume 时会交叉核对中央归属，发现冲突先协调。保存返回的完整 session 和 snapshot，再按原规则持锁。
4. 本地动作记录缺失时，先调用 `native.recoverActions(session, savePage)`。savePage 将每页保存到本轮专属 recovery-actions/page-N.json；helper 按中央 runActionRefs 分页发现全部状态的动作 ID，再用现有 get 读取完整最小回执，拒绝跨轮结果和缺页，仅返回计数摘要。旧服务缺少该索引时明确停止依赖历史的写入，保留原轮，不把缺能力当成零历史。另按原流程核对全工作流的未知动作。已确认的动作复用回执，unknown/intent 先核对原 provider/job；恢复回执不会恢复已丢失的原件或报告，也不伪造采集覆盖。
5. 从返回 session 生成本轮执行队列。`workflow.py execution-plan --input INPUT --output PLAN` 的 INPUT 是 `{run: session, progress: savedProgress}`；首次省略 progress。队列按冻结配置生成五类入库的独立阶段、每个评价来源身份和周报阶段。准备样本不会自动完成 collect。当前 `next` 是可执行的待办；某类来源阻塞时其他独立类／来源仍能出现。用已恢复回执及各业务技能的完整性检查重建可证明的阶段，证据不足的来源范围仍需重新只读采集；不因进度文件缺失重放已确认或未知的写入。

每日／周报的当前窗口若已有相同业务配置和集成版本的最近成功轮，recoverRun 返回 `alreadyCompleted:true` 及原轮元数据，不新建运行或授予写入绑定。读取原轮回执核验后交付去重结果，保留当前包尚未实际执行新业务周期的验证区别；不借旧成功轮登记新包首次业务执行。评价同窗仍可能出现新评价，继续开启本次采集。用户明确授权、带 prepare_backfill 确认的补跑也不被此去重分支跳过。

## 执行队列和证据

执行 `next.stage` 对应的 [业务定义](execution.md)，采用该条 `scope` 中的完整范围。每阶段成功后保存实际核验输出，再原子更新 progress：

```json
{
  "runId": "central-run-id",
  "bindingHash": "execution-plan-returned-hash",
  "completed": {
    "task-id": {
      "scopeHash": "task-returned-scope-hash",
      "evidence": [{"path": "/absolute/run/proof.json", "sha256": "actual-file-sha256"}]
    }
  },
  "blocked": {}
}
```

证据必须覆盖该条完整 scope：每日按精确门店／日期保存筛选、全部原件及发布／零条对账；评价 collect 按来源身份保存筛选、页码、总数及去重 ID；周报保留完整性与经营建议检查。索引引用保留的核验输出／回执文件，不直接引用稍后会清理的原件。只有样本或部分门店时仍保留待办。阻塞写 `blocked[taskId]` 的准确原因；条件恢复后移除该项并重试原任务。每次更新后重新运行 execution-plan，文件缺失／哈希变化、跨轮进度和跳过前置步骤均会拒绝。

队列是本地进度索引，不是外部成功证明。上传、同步、发布和邮件仍须原生 claim/check、真实回执和完整读回。通知启用但无合格新稿时保存该轮新稿筛选结果；已投递则核对原邮件及持久去重身份，作为该阶段证据。邮件失败只阻塞通知／最终完整归档，不阻塞独立发布与同步。禁用发布不会跳过身份、审阅表和同步的前置步骤。

## 对话轮次与浏览器资源

临时浏览器标签通常在对话轮次结束时关闭。尚有来源工作或等待中的导出时，先持久化当前筛选、导出任务及下一步，再对本轮确需接续的标签调用宿主文档支持的 `tab.markHandoff()`。这个标记只保留浏览器资源，不表示任何业务已完成。正式收尾时正常清理临时标签。

续轮先读取当前浏览器文档／清单，以实际存活标签恢复；标签已不存在时，在同一选定浏览器重新打开已核验入口并恢复筛选。REPL 中的函数、闭包及定位器不是持久检查点，环境重置后重新定义；不要从保存的 JSON 恢复旧对象。租约过期时先 resume 原轮，再继续来源调用。浏览器明确不可用时按 browser.md 回退 Chrome，不反复排查 IAB。

## 收尾与下一轮

`readyToSummarize=true` 只表示已保存全部阶段证据。再核对中央动作及各业务技能的完成门槛，调用 closeRun 并读回 finishedAt/summary；随后登记真实 firstRunVerification，按 [临时文件清理](runtime.md#临时文件清理) 完成本地收尾，再释放本轮锁。清理受阻时保存待清理清单和原因，交付中央业务结果与清理状态。遇到无法继续的真实阻塞，保存证据和剩余队列，按宿主 Goal 的阻塞规则处理；不要以另开新日期轮消解原轮。

后续自动触发仍使用原任务 ID／时间表。真实首轮成功和去重空跑分别记录；已经发出的周报或评价邮件不为验收再发一次。普通运行不更新包，显式更新前先核对旧轮固定版本并保留所需依赖。
