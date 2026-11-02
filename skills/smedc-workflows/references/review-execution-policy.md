# verified-review-operations，版本1

中央只保存这个闭合预设 ID/version 和必要的忽略身份；不是任意系统 prompt 或可执行脚本。`workflow.py review-task` 从冻结 snapshot 生成本轮 task.json、包内 logger 路径和按命名空间的映射。版本不支持则停止，不能悄悄换规则。

## 保留的业务与证据语义

- 不可识别 emoji／图形仅从客户原评价中省略，保留可读文字并另记省略；它不是错误，也不单独阻止起草、同步或清理。省略后为空按纯评分处理。
- 当前已核实平台观察是同一完整身份的来源权威。完整身份含当前认证组织、企业、渠道、标准店、规范评价时间、准确昵称、feedbackId；POI 验证来源店。相同完整身份 upsert／unchanged，不同完整身份独立保留；缺少的观察字段省略或保留同身份原值，不抹去已有事实。写后唯一完整身份的全部观察字段及独立行读回，仍执行新旧保护。
- 问题台账 schemaVersion=2，items（业务）、evidenceItems（证据）、resolvedItems、resolvedReviewIssues、waivedItems 分别保存。业务按完整身份或准确覆盖范围去重；关联全部相关 runId。resolved 必须有核验证据与时间，后轮完整覆盖可以销项但不把旧执行历史改成功。活动起点 state.issueTrackingSince 保留，不自动扩大历史。
- state.issueCounts 分别计算 confirmedBusinessIncomplete、businessCoverageUnverified、businessUnknown、evidenceNotes；unresolvedCount 是 items 数量。更新前持锁并核对旧文件 SHA，保留已有字段和未解决项，不能整份替换为空数组。
- 业务已全部核验且本轮无业务待办、收尾完成时，纯日志缺口可不阻止聊天归档；文件清理有独立门槛，涉及未恢复证据的材料继续保留。七项 cleanup gates 与中央 confirmed 证明仍必须通过。

## 实际调用审计

包内 `scripts/audit_log.py` 与 `scripts/audited-tool.js` 是通用实际实现，凭据脱敏后完整保存错误，不截断、不重试、不修改原工具结果。每调用单独文件，start 原子落盘/fsync 后才派发；finish 必须先于恢复。startedAt 是客户端派发前检查点，不是服务收到时间或评价时间；elapsed 只代表实测耗时，不能猜模型／网络分解。

可通过 functions.exec 调用的工具：读取 audited-tool.js 到宿主 store，求值得到 audit，按实际 logger/runDir 传入，再包装真实工具调用。可为本轮 tools 创建固定白名单包装，让 native adapters 内部的每个实际工具都经审计。不要包装 logger 自身，避免递归。

```javascript
const audit = (0, eval)(load("reviewAuditSource"));
const rawTools = tools;
const audited = { ...rawTools };
for (const name of discoveredWorkflowAndProviderToolNames) {
  audited[name] = (args) =>
    audit(
      rawTools,
      loggerPath,
      runDir,
      {
        stage: currentStage,
        tool: name,
        effect: writeNames.has(name) ? "external_write" : "read",
      },
      () => rawTools[name](args),
    );
}
const native = (0, eval)(load("workflowAdapterSource"))(audited, {
  localScript: scriptPath,
  saveOutcome,
});
```

工具白名单来自当前官方工具发现，不能来自中央业务文字。最多3个读取并发，小批 allSettled 逐结果保存；写入保持现行幂等和 unknown 核对。保存日志失败：派发前失败不执行；派发后失败不能认定业务未执行，应保留结果并核对。

必须直接使用 cua_repl 的浏览器调用：先 `audit_log.py start --run-dir RUN --meta-json META`，紧接一次真实调用；下一步先 finish，保存凭据脱敏的完整错误，再恢复。effect 为 read/local/external_write。外部写报错保守 unknown；只有明确 confirmedNoCommit=true 加 verificationEvidence 才能记确定失败。异步 session_id 保留原会话，不重发；未知结果后来核对，用同一 callId finish，旧 outcome 保留。

本地命令用 `audit_log.py run --run-dir RUN --meta-json META -- COMMAND ARGS`，只包装一次；不在命令参数传密码、Cookie 或 token。每轮结束执行 `audit_log.py check --run-dir RUN`，持久化 pendingCalls/externalWriteUnknown 及独立业务／证据处置。日志完整不替代业务核验。

## 迁移识别

`review-execution-policy.json` 声明当前精确语义。迁移器仅对四个已知 policy 字段逐项核对；引用路径只允许已知 logger／wrapper／reference 文件名，换机时生成本包的准确路径，不沿用旧机路径。任何新增字段、改变规则或不明引用返回 source_conflict，先核对再迁移。

ignoredReviewIdentities 每项为 source（产品／账号／渠道／优先POI或准确全名）、feedbackId、reason、purpose=exclude_source_record；它是有意排除，永远不是完成动作或发布回执。旧 poiId/source/feedbackId 只有唯一匹配已确认来源账号与映射才可转换；歧义阻塞。新机直接从中央配置恢复，不依赖旧机器的私有台账路径。
