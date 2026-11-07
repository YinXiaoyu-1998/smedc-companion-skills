> **WorkBuddy 宿主优先级**：本文件涉及浏览器选择、登录态、保存框、下载等待、
> 宿主工具与定时任务的段落，一律以 `workbuddy/HOST_MAP.md` 与 `workbuddy/WORKFLOWS.md`
> 以及 SKILL.md 顶部的「WorkBuddy 宿主适配」章节为准。上游专有接口名已替换；业务筛选、
> 原件校验、证据与清理门槛不变。此文件由 `build_overlays.py` 生成，请勿手工编辑。

# 安装、准备检查和 原宿主

## 官方版本和企业设置

先使用核心技能完成官方安装／安全升级／登录。工作流包最低兼容 launcher 为 manifest 声明的版本；这不是安装批准 pin。核心仍批准较旧版本时，显示“工作流暂不可用，等待官方已验证发布”，不自行装候选版本、npm latest 或改现有 MCP 项。普通 SMEDC 功能继续可用。

从当前宿主发现八个官方工作流工具，调用 `list_enterprise_workflows`。必须取得成功的实时兼容描述及企业目录／官方设置入口；静态 tools/list 不证明服务已发布或有权限。管理员选择业务企业，复用已有设置和授权；不存在时在官方“自动任务”页建立草案。不要拼组织 URL。普通账号不能登记、运行或借 admin 代理读取数据；每项业务读取仍需对应类别、门店及密级权限。

首次核心安装仅介绍三个选项并报告可选状态。用户选定后，在官方 companion 默认分支的已记录 Git commit 检出源码；读更新后的文件、比较完整子树，不覆盖更新的本地定制。执行 `workflow.py install`，输入由 agent 准备：

- `selected`：manifest 的一至三个准确工作流 ID。
- `sourceSkillsRoot`：已核实来源检出的 `skills` 绝对规范路径；`sourceRevision`：该检出实际 Git commit。
- `destinationRoot`：当前用户规范 `~/.agents/skills` 路径；`recoveryRoot` 可选，必须在发现目录外。

只复制选择闭包及本工作流包，不安装核心或其他 companion。重复且相同内容复用。差异先报告并保留本地改进；完成差异审阅后才通过 `expectedInstalledHashes` 指明批准替换的精确旧哈希。替换保留目录外恢复副本、验证逐文件哈希，宿主加载新内容后才清理恢复副本。普通定时运行不得执行安装或更新。

## 每任务准备检查

读取运行环境真实工具文档。检查结果用 `workflow.py readiness`，`checks` 按 manifest capability 名给出 `status/nextStep`，另给 `checkedAt/workflowType/mailEnabled`。状态只能是 ready、needs_configuration、needs_login、permission_denied、unsupported、unavailable。未实际检查的能力是 unavailable，不能填 ready。

- configuration：实时兼容服务、已保存精确企业／来源账号／来源集团品牌绑定、门店映射和独立任务选择。未知门店 needs_configuration；不是闭店。
- permissions：当前 admin 及对应内容权限。未通过前不读本地待上传业务原件。
- meituan_erp / meituan_reviews：先按 [浏览器选择与恢复](browser.md) 选择实际可用的 bsk Agent Window 或本机 Chrome，再分别检查正确来源账号和真实会话；不搬 Cookie。bsk Agent Window 不可用时必须检查 Chrome，不能提前停止整轮准备检查。
- download / file_format：每日入库按原技能对当前授权范围作小样本导出，核对筛选、原件完整列、行数及来源身份；周报检查官方范围下载。评价导出是可选采集路径，不支持当天导出或零样本时保留真实 download 状态，另验证 meituan_reviews 的逐页读取；file_format 验证审阅表生成和独立重开。页面打开不是导出验证。sampleStatus 只用 verified、no_sample、not_checked；具体方法（如合成审阅表回读）放 nextStep，无样本不伪称导出成功。准备检查与首次实际运行分开。
- workspace：实际可写的专属本地工作目录、文件权限和精确清理归属；不把家目录或共享 Downloads 当 run 根。
- dependencies：所选技能完整子树、版本／哈希及运行依赖。表格和文档依赖通过宿主 `本地运行环境探测` 获取，不硬编码库路径。评价解析需 openpyxl；工作簿复用 本地工作簿依赖 构建器。
- host_schedule / host_timezone / host_model：原生独立本地 cron、系统 Asia/Shanghai、实际支持的模型与推理选项；缺失就暂停。迁移保留旧任务模型和推理设置，不擅自降级。
- assignment：中央指定 installationId、epoch 与本机登记一致。到期租约不自动授权另一台机器。
- email_identity / sent_mail_lookup：仅影响启用的邮件阶段，分别检查 原生邮件连接器（本宿主不可用） 当前身份和可用的已发送查询／读回。原生邮件连接器（本宿主不可用） 缺失仍允许本地报告和独立采集。收件人可为任何邮箱，不增加抄送、密送或隐式收件人。

通过 `manage_workflow_installation` register / record_checks 保存随机非秘密 installationId、设备别名、包版本和真实检查。`firstRunVerification:not_run`；真实已授权运行后才能记录 verified / partial / failed。不要为检查发送测试邮件或发布顾客回复。

## 实际宿主安装

不要写 宿主定时任务定义。使用 `native.install(input,journal,save)`，它调用当前工具的 `automation_update` create PAUSED，notificationPolicy=failed_runs_only，然后原生 view 并由精确 ID 读取原生定义核验。只读 TOML 是该宿主工具明确支持的检查方式。

`input` 为 `workflowId/name/prompt/rrule/model/reasoningEffort/timezone/platform/projectId`。本地 projectId 来自 `list_projects`，不得沿用旧机项目 ID。新机也可传 `projectId:null`，但须先实际验证隔离工作目录并传 `workspace/workspaceVerified:true`；prompt 明确该绝对目录。回读必须是 `target.type:projectless`。中央快照 projectRef 的 `projectless` 只是描述，绝不把它传给实际 projectId。若宿主拒绝 projectless，选择现有本地项目或请用户在 原宿主 添加目录。

一个工作流一个实际任务。分发包不提供全企业统一的默认运行时间。新安装按这台电脑通常保持开机的时段提出建议，取得用户对具体时间表的确认后再安装；未确认时保持待配置，不创建猜测日程。迁移和更新从原宿主实际读回日程，原样保留 RRULE，并核对预期发生时间；多个非整点时刻须正确保留组合，不扩成额外次数。时间只在 原宿主 修改，修改后读回并 record_host；不另建中央调度。

提示词明确请求“创建并执行一个持久 Goal，按 smedc-workflows 的定时运行入口完成该工作流”，并携带工作流 ID、enterpriseKey、installationId、锁定包版本／Git commit、安装锁路径和本机专属工作路径。实际执行入口见 [invocation](invocation.md)；不复制全部门店、邮箱、品牌策略和历史记录进去。安装锁保存在专属安装目录，避免引用一次性修复目录；清空运行缓存仍须保留包／依赖锁。

`journal` 在首次创建前经 `save` 原子落盘。未知创建结果留 createPending；按本轮返回 ID 精确恢复，或在用户可见宿主中定位本次创建记录，不能重试制造重复。保存 readback hostSnapshot 到中央 `record_host`。缺项继续保存 PAUSED 任务；准备就绪后按中央配置确认、指定安装／接管、启用状态及宿主原生 update 的顺序激活。实际激活仍需读回，不把 register 当启用。

更新前读当前未完成 run 的包版本；旧包不可用则阻塞旧轮。暂停受影响宿主任务、保留中央设置／完成回执，更新所选子树、检查并按原授权恢复；不重建业务配置。

旧的原始定时 prompt 尚未执行中央租约／控制检查，云端撤销不能停止它们。新电脑预检、中央导入和新任务 PAUSED 安装可先完成；实际启用必须等用户确认的切换窗口，取得旧任务已暂停或旧设备已退役的精确证据。没有旧任务的新企业也须明确确认 no_legacy_tasks。assignment 检查记录此事实，不能仅因为云端没有旧租约就自动启用。

调用 `native.setHostState(input,journal,'enabled',save)` 时，input.handoff 为 kind=legacy_paused/old_device_retired/no_legacy_tasks、acknowledged=true、proofHash 和 confirmedAt；证据来自本轮准确宿主读回／明确退役确认并在私有文件保存。当前中央 assignment/control/installation 也必须允许；函数原生 update 后读回并 record_host。合作式撤销保证只适用于已采用这套协议的新安装，不声称阻止旧原始任务或任意获授权管理员。

## 非技术用户的运行组件准备

以上命令／JSON 都由安装代理准备和执行，用户只选择任务、在官方页面登录及审阅准确业务差异，不要求用户写文件、找隐藏目录或手工改命令。代理先调用真实 本地运行环境探测，检查返回的 Python >=3.11、Node >=22、openpyxl 导入及 artifact 模块；用返回的解释器路径传给 native 的 pythonExecutable，Node 引擎基础安装仍由核心负责。

有可用 Python 但缺 openpyxl 时，用户已选择该工作流的安装授权内，可在专属工作目录创建当前用户 venv，再安装所选 review skill 的 requirements.txt；不做全局 pip、不修改系统 Python 或其他任务环境。优先复用已验证的 bundled 库。复制原版工作簿 MJS 到专属 builder，核对 SHA，node_modules 只链接当前宿主实际返回的只读库目录。缺 Python、artifact 模块或导出／预览能力且没有宿主支持的安装方式时，精确记录 dependencies=unavailable，向用户说明“当前运行组件不可用，任务保持暂停；请启用或更新相应 原宿主 组件后继续”，不能假完成，也不让用户手工编辑 JSON。基础 SMEDC 继续可用。

显式包更新使用现有本机 journal/taskId；先暂停并实际 readHost 回读当前日程／模型，把这些原值带给 native.install 的 update=true，只改已审阅的新版本 prompt，更新同一任务后回读。普通安装／运行不自动更新；不得用默认日程覆盖用户在 原宿主 修改的时间。

最终启用统一调用 native.activate。它先验证明确旧任务暂停／退役（或无旧任务）的证据与实际新宿主 PAUSED 状态，再确认当前指定安装和 control.active 权限、记录 assignment 准备检查、set_state enabled，最后原生启用和回读。control.active 本身只是运行许可；只有满足新服务的完整就绪／指定／启用条件且选择店内订单的每日任务才切换来源要求。周报、评价和普通草案不会触发该切换；切换前不得擅自调用 set_state enabled。

代理先调用 native.prepareWorkspace({path,workflowId,installationId})，得到真实写入探针通过的 workspaceRoot/statePath/runsDirectory/builderDirectory；返回值均为规范物理路径。用户选择的 /tmp 等系统别名或文件夹别名先在此明确解析，随后所有状态、锁、原件与清理仍使用严格规范路径保护，不放宽 saveLocal 的符号链接限制。已有非空无归属目录、共享根目录或其他安装的目录会阻塞，代理应选择专属子目录，不让用户手工修路径。
