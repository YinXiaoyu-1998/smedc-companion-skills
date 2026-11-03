# 定时运行入口

安装／更新与业务运行分开。定时 prompt 明确请求创建并执行一个持久 Goal，并携带工作流绑定、固定包版本／源码修订、安装锁路径和专属 workspaceRoot。Goal 使用宿主 `get_goal/create_goal/update_goal` 生命周期；普通技能调用不自动创建 Goal。它让未完成工作能在同一聊天接续，不扩大权限，也不替代业务核验。宿主没有这些工具时，将该执行模式记为 unavailable，不创建另一个调度器。

## 启动和恢复

1. 核验安装锁和所选依赖，按 [runtime](runtime.md) 加载 native adapter。调用 `native.beginGoal({workflowId,goalRequested:true})`；只在定时 prompt 的显式 Goal 请求下传 true。同一聊天续轮复用已有 Goal，不覆盖别的 Goal。
2. 读取当前身份、配置、指定安装及当前权限。state.json 是本地缓存；缺失时用已核验安装锁、prompt 绑定和中央 installation/hostSnapshot 重建，先核对实际任务 ID、日程、模型和目录归属，不导入旧机路径。迁移回执和 unknown 动作仍从中央恢复；清空本地记录不等于清空业务历史。
3. 按 [installation](installation.md) 刷新实际就绪检查。准备检查只决定哪些阶段可执行；接下来调用 `native.recoverRun(input)`，它分页寻找中央未结束轮并恢复原 runId／窗口。无未结束轮才以 `workflow.py window` 的窗口开轮；明确补跑仍走 prepare_backfill。传旧 state 的 resume 时会交叉核对中央归属，发现冲突先协调。保存返回的完整 session 和 snapshot，再按原规则持锁。
4. 从返回 session 生成本轮执行队列。`workflow.py execution-plan --input INPUT --output PLAN` 的 INPUT 是 `{run: session, progress: savedProgress}`；首次省略 progress。队列按冻结配置生成五类入库的独立阶段、每个评价来源身份和周报阶段。准备样本不会自动完成 collect。当前 `next` 是可执行的待办；某类来源阻塞时其他独立类／来源仍能出现。

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

## 收尾与下一轮

`readyToSummarize=true` 只表示已保存全部阶段证据。再核对中央动作及各业务技能的完成门槛，调用 closeRun 并读回 finishedAt/summary；随后登记真实 firstRunVerification、处理本轮锁和按规则清理。Goal 完成以完整业务结果及中央收尾为依据。遇到无法继续的真实阻塞，保存证据和剩余队列，按宿主 Goal 的阻塞规则处理；不要以另开新日期轮消解原轮。

后续自动触发仍使用原任务 ID／时间表。真实首轮成功和去重空跑分别记录；已经发出的周报或评价邮件不为验收再发一次。普通运行不更新包，显式更新前先核对旧轮固定版本并保留所需依赖。
