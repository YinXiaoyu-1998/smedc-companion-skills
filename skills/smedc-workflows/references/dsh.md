# DeepSeek Harness（macOS）

## 安装与调度

验证已登录的 DSH 桌面本机 PTC 会话提供 `run_code`、`bash`、`schedule_create/view/edit` 与官方 SMEDC MCP；只支持具有这些实测工具的桌面宿主。选一个专用会话用于每个工作流，保存其真实 session ID、实测模型/推理等级、当前工作目录和安装锁。DSH Schedule 读回的是会话目标和日程，模型必须从目标会话本身核验。普通 headless CLI、其他 preset 或远程会话未通过准备检查时记 unavailable。读取中央 capability.dshMinimumLauncherVersion；只有已部署的匹配服务与核心已批准的安装版本满足它时才可登记。不要安装候选版或修改核心 pin。

使用真实时区 Asia/Shanghai，并由用户确认开始时间与重复规则。传 `DTSTART;TZID=Asia/Shanghai:…\nRRULE:…` 给 native.install。保留日程中的时分组合，不从旧规则猜测时间。先验证专用工作区与目标会话，再由适配器创建只含无业务动作的草案 prompt，读回该 ID、暂停并写入正式 prompt。未知创建结果先查原任务，不重复创建。登记 host=dsh，projectRef 是目标 session ID。启用按安装参考的原有接管、指定安装和中央授权顺序操作，再原生恢复任务并读回；仍须独立验证首轮。DSH 以同一会话串行接收调度，中央每工作流只有一个指定安装。

正式 prompt 明确调用已锁定的 smedc-workflows 定时入口，携带 workflowId、enterpriseKey、workflowType、installationId、包版本/commit、锁路径和 workspaceRoot。taskId、已验证的 prompt 和 rrule 由安装日志读回；不要把任务 ID 写进需要在创建前生成的 prompt。DSH 定时触发不是 Goal 工具要求的人工请求。按中央 runId 和检查点恢复，后续调度可以接续原轮；不从定时消息调用 create_goal 或擅自恢复人工 Goal。宿主保持运行是已验证前提，完全退出后的自动恢复须另验。

## 运行封装

使用 DSH 的 `run_code`，在 PTC 程序中从已核对安装锁的本地文件读取脚本并求值，不把脚本输出到聊天。若使用 bash 读取，检查退出码和完整性，超过输出上限时按片段读回并核对哈希。用与 Codex 相同的工厂，加 `host:"dsh"`、`dshSessionId`、官方 binding、`localScript`、`pythonExecutable` 和真实的 `saveOutcome`。所有路径从专属安装解析。包或工具不符时保留原进度并明确阻塞。读取 workspace 本地 Python 和依赖，实查 openpyxl 和已有审阅表构建器；不假定 Codex 的依赖工具存在。runLocalCommand 识别 DSH 的 foreground 结果；提到后台 job 时核对原 job 及本地状态。长工具经过 withLease 并用实际计时器续租；恢复中不重放未知写入。

在本轮输入提供安装日志中的 taskId/prompt/rrule。适配器在 start/resume 前验证原生任务与中央登记一致。跳过 Codex 聊天归档和 Gmail。成功、阻塞、已确认和未知均沿用现行收尾约定。

## BrowserSkill

使用已安装并绑定的本机 BrowserSkill CLI 和用户正确的 Chrome 资料。读取已安装 browser-skill 的 cooperation、tabs-and-profiles 和 files 参考。校验具体资料、页面登录账号、集团和中央映射。使用专属 Agent Window、明确 tab、fresh sync 与 ref；页面漂移重新观察。关闭当前会话前保存筛选回读、进度、导出任务身份及下一步。重开会话后重新绑定 tab 和 ref，再按已保存的申请时间/类型/范围定位原导出。绝不复制 Cookie 或用隐藏接口下载。

- 自助营业/菜品先选核验的查询方案，再设冻结日期及门店。被遮挡的菜单、组合框及按钮用已确认的键盘焦点和选项操作，等待并读回。菜品异步导出若弹窗内无法跳转，用现有独立下载清单标签，记录本次任务行并匹配名称、范围和申请时间。
- 订单确认营业日期、门店及订单状态后再导出。收货单在实际页面确认“收货日期”选项后点选并回读，取消“待收货”，确认十店这类计数与准确配置名单一致后查询。逐页选择、清空再翻页；用单号集合核对 ZIP、XLSX 状态及实际收货日。
- 捕获确定会开始下载的当前 ref（直接导出的最后一步或异步清单中本次任务的下载按钮）。用 `native.captureBrowserDownload(session,{runRoot,filename,browserSession,tabId,contextId,ref})` 将字节写入本轮规范私有目录，检查返回的文件路径及哈希。随后按对应业务技能对账列、实际门店、日期、状态及行数。捕获失败或结果未知，先核对原任务、下载状态和保存框；只在原技能许可时有界恢复。不能将共享 Downloads 的最新临时文件归给当前任务。
- 评价使用经营宝框架和实际门店单选，按 [DSH 评价参考](../../reply-meituan-reviews/references/dsh-compat.md) 逐 POI × 渠道。允许读取完整七天超集再过滤冻结窗口，但必须逐页读满、按评价卡片区分客户与商家回复时间。跨店查询或切店后的导出可能漏条或返回不同门店。无稳定评价 ID 的卡片仅作本地采集证据；禁止生成替代 ID，缺失身份阻塞对应同步、发布及依赖该身份的新稿邮件。

## 邮件

已启用通知时读 [SMTP](smtp.md)；邮件准备检查用 `host:"dsh"`。Gmail 只适用于现有 Codex 路径。
