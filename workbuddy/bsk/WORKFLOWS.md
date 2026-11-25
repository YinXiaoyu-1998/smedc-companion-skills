# Three runbooks（browser-skill profile）

本文件是 **browser-skill profile** 下三个工作流的运行要点，随每个已安装 skill 分发。
业务定义（原件留存、七项门槛、字段口径）仍以各业务 skill 正文与中央冻结快照为准；
网页操作的权威命令表见 `workbuddy/references/browser-skill.md`。

## Common start（每次调用）

1. 宿主 `automation_update` 触发一次对话 = 一次 invocation；同一 run 的续轮不是新一轮。
2. `wb_state.py resume --root <runRoot>` 校验本地状态哈希链；有未结束轮沿用其 runId、
   窗口与绑定。只有中央状态确认无未完成轮才可 `init`。
3. **浏览器前置（本 profile 特有）**：`BSK_AUTO_START=0 bsk status --json`、
   `browsers --json`（取 instance_id）、`doctor`。daemon 不在时用宿主后台任务拉起
   `BSK_AUTO_START=0 bsk daemon start --foreground`，并在**另一次**调用里复查 status。
   扩展未连接时按 doctor 提示处理。这一步由 agent 完成，**没有员工每次点击的授权弹窗**。
4. 读取当前身份、冻结配置、指定安装与权限卡；外部写前复查控制、assignment epoch 与租约。
5. 中央 `upload` / `download` / `review_sync` / `review_publish` / `email` 走原生
   claim/check/record 序列；长阶段有界续租，结果不明不重放。
6. 浏览器来源读取：`bsk session start --browser <instance-id> --no-focus` →
   `navigate` → `cooperate sync --policy target`（取 context_id / observation_id）→
   `snapshot` / `observe`。**每次导航或人工输入后重新 sync**；iframe 内控件用 `@eN` ref。
   下载用 `bsk download <trigger> --out <绝对路径> --session <SID> --context <CTX>
   --observation <OBS>`，一步点击+捕获+落盘；结束后 `bsk session stop <SID>`。
   重新核对来源账号、集团/品牌、完整门店名与日期筛选。
7. 每阶段保存已核验证据（筛选、原件、哈希、读回）再更新进度；缺失范围保留 pending，
   阻塞用 `mark-blocked`。
8. 中央关轮并读回后才 `wb_state.py close`；邮件阶段 blocked 时 outcome 为 `partial`。

## 1. 每日美团入库

窗口：前一完整营业日。只处理 `snapshot.configuration.datasets` 启用的数据集，各自可独立恢复。

- `business` / `dishes` / `in_store_orders` / `takeaway_orders` / `combo_sales` /
  `delivery_ledger` 分别对应各自的来源 skill。保持 `settled_only` 订单范围、
  `全量数据` / `全量菜品` 选择、异步导出任务 ID、有界等待与逐页对账。
- 导出点击前先 sync；`bsk download --out` 落盘后仍做本地校验：非空、ZIP `testzip()`、
  XLSX `[Content_Types].xml` / `xl/workbook.xml` / 工作表行数、日期与查询条件一致。
  `download_path_mismatch` 时先查浏览器下载列表，不盲目重复点击。
- 上传只走核心 skill 契约；只有 `published` / `applied` 回执才允许确认与逐文件清理。
  零结果记 `observed_zero` 并附证据，区别于缺来源/下载失败/缺列。
- 上传绑定已认领的中央动作，用 `query_jobs` 读回；保留被拒回执并记录终态。

## 2. 美团 / 点评评价操作

窗口：前一日 + 当天。采集前读 `executionPolicy` 与评价 skill 的 scheduled-run reference。

- 从冻结快照生成 `task.json`，按 `sourceIdentityMappings` 精确遍历，不按渠道交叉扩展。
  保留已有回复、跳过仅评分行、保持九列、精确时间/评分、来源回复与 feedbackId。
- `review_sync`：冻结完整身份/载荷/existingId，claim 后逐页读回并全字段比对再记录。
- 新稿通知：**blocked**（邮件身份不匹配）。`wb_mail.py plan` 写本地交付记录，不发信。
- `review_publish`：仅在 `publication.enabled` 且门店/渠道在中央现行持续授权内时执行；
  claim/check → 发布 → 读回真实商家回复 → 记录 `provider_readback`。
- 归档仍需完整七项门槛 + 中央未解决动作证明；邮件 blocked 不满足它们。

## 3. 自然周经营周报

窗口：上一自然周。沿用 business-analysis 链：
`build_query_plan` → 官方范围下载 → `load_partition_extract` → `assemble_query_bundle`
→ `run_weekly_report` → advisory prepare/attach。

- 传完整门店名并在提取后再次精确匹配过滤；分组来自中央 `groups`，每店只属一组。
- 保持关联、数量、餐具费规则；数据缺口/部分读取/失败分别记录。
- 只有事实/建议/HTML 完整性检查通过的报告才进入交付；无原生邮件时
  `wb_mail.py plan` 记录 blocked，最终 HTML 本地保留（`retain_final_report`）。

## Reporting

正常完成只留简短结果。精确说明哪个阶段 blocked 及原因、保留了哪些证据、剩余范围是什么。
不要把 blocked 邮件阶段或本地交付描述成已发送，不要把本地状态文件描述成中央回执。
