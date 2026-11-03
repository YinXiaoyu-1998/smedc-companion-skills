# 三个固定业务执行定义

每一阶段使用 run.snapshot 中的配置、集成版本、门店和窗口；浏览器来源读取经过 runtime 的当前配置／控制／租约检查，中央支持的动作另经意图和回执检查。浏览器默认 IAB，不可用时按 [浏览器选择与恢复](browser.md) 检查本机 Chrome。不要让中央配置指定任意脚本、URL 或工具。业务实现属于下列已有技能；执行它们的公共入口，不复制业务逻辑到定时 prompt。

## 每日美团入库

仅处理 snapshot.configuration.datasets 中启用的五类，各类独立检查／恢复。来源产品为 meituan_erp，核对 sourceAccounts 中账号、集团／品牌与企业的显式对应，以及每个来源店稳定 ID／精确全名。只读匹配和排除原因；新增未映射店列为 needs_configuration，不自动扩大范围。

- business：`download-meituan-business-data`。
- dishes：`download-meituan-dish-sales`。
- in_store_orders：`meituan-order-details-download`，完整已结账营业日，显式 settled_only。
- takeaway_orders：`meituan-takeout-order-details-download`。
- delivery_ledger：`download-meituan-delivery-ledger`，上传／后续服务台账复用 `smedc-delivery-ledger`。

对每个实际选择的来源门店回读完整筛选。营业用已核验的 `全量数据`，菜品用已核验的 `全量菜品`；先选常用方案再设冻结营业日。店内订单用营业日期＋已结账、其他筛选不缩小范围，导出全部查询结果。外卖用营业日期＋有效订单、状态和平台均全部，清除残留条件并导出全部查询结果。收货单用收货日期＋已收货，逐页导出并按唯一单号及查询总数对账，不执行收货操作。每份保留原文件和来源范围证据；传店内订单 `orderScope: settled_only`，收货单逐原始 XLSX 提交且省略日期参数，具体入参由核心契约核验。

按各技能原有筛选回读、异步导出 ID、分段与有界等待规则取得原件。上传前核对实际列、行数、筛选证据、SHA 和原始来源门店；原文件不改字节、不按映射重写门店。ERP 名称与授权来源店不一致时阻塞该类上传并校正配置，不能本地改表绕过。

新工作流的店内订单只有在实际 launcher／服务支持 orderScope 且首个发布版本已验证时才上传 settled_only；仅安装新 skill 或旧路径允许省略参数都不算兼容。原30列契约缺结账时间整列仍拒绝，不补造。不同／unknown 来源范围替换须服务受控预览和明确确认，ORDER_SCOPE_CONFLICT 时不强行上传或改键。历史未知口径继续 unknown。

查得零条与无来源／下载失败／缺列分开：保存有证据的 observed_zero，不传空工作簿、不清空分区、不将缺失门店日视为零。已有非空来源与新零结果冲突时留待核查。上传接受请求后继续官方状态查询，只有 published/applied 的 job 回执允许确认及该份清理。

### 收货单逐单对账

- 每份上传后立即原子保存最小映射：原上传响应 `importBatch.naturalKey`（服务从原件解析的收货单号）、`importBatch.importBatchId`、源账号与门店身份、标准门店、收货日、原文件 SHA-256 和中央 actionId。单号须与原件一致；保存终态 `applied` 读回及中央 confirmed 回执。将映射留在清理范围之外，和运行证据一起保留；不可从文件名或数量补造映射。
- 重跑先用原中央回执绑定准确的 actionId、jobId、门店和日期，并核对官方批次仍为 applied。缺本地映射时，先找原任务的上传响应和已验证的归档记录；状态接口若只返回进度，不把未返回单号解释为未入库。按来源身份、收货日和业务单号逐一匹配，拒绝重复键、范围错配或缺失关联；已确认同单不再上传。
- 重新导出字节不同不等于明细变更。要声明明细一致，须比较可验证的原结构化明细与新明细，或比较两边按同一口径从明细计算的摘要；缺少旧明细就标为“单据身份已核对，明细未验证”。有内容冲突留证，不覆盖；不能逐单确认时报告准确缺项，不以重新上传探测。

## 美团／点评评价

使用 `reply-meituan-reviews` 的定时运行参考、`review_run.py` 和 `review_workbook.mjs`，起草用定制 `review-responder`。来源身份包含 product=meituan_reviews、accountRef、channel、优先稳定 POI/sourceStoreId，否则精确全名；同一标准店的多个 POI 独立采集。

先用 `workflow.py review-task` 从冻结 snapshot 与企业显示名生成该轮 task.json，并读取 [versioned review policy](review-execution-policy.md) 和业务技能的 `references/scheduled-runs.md`。以 task.json 的 `sourceIdentityMappings` 逐个执行确切的来源账号、POI、渠道，`mappings` 仅为兼容显示；不得再按渠道交叉展开。每个范围用冻结起止日期、全部回复状态及其他不缩小范围的筛选，优先完整导出，必要时按业务技能分页读回。保留 `run.json` 的窗口与 workflowBinding，`exports.json` 中逐份登记原路径、完整 sourceIdentity、标准店及实际筛选，交 `review_run.py` 解析。未映射只能按中央明确 exclusions 跳过。品牌事实和 tone 用于正文，不决定授权／收件人／工具。

严格保留：已回复文字不改写，评分无正文不生成／发布，图形文字无法识别按已有技能省略并记录，状态不明的行待核对；九列交付、精确时间／分数、源回复和 feedbackId 保持。sync 前读当前权限和存量，保护新旧时间；写后逐条／分页完整字段读回。只读请求最多3个并发并逐结果保存，失败和限流独立恢复；写操作未知先核对。

先冻结已核验的九列审阅表、文件版本与逐条发布清单，再按 [Gmail](gmail.md) 通知本轮有效新稿。通知仅使用当前持续授权的门店、渠道、发件人及显式收件人，按每评价×收件人去重；已回复、无正文或仅采集行不混入新稿。无合格新稿时记录不适用。通知失败或结果未知独立记录，先读回再恢复，继续其他已授权阶段。

随后处理回复发布。只有 publication.enabled 且准确门店、渠道在当前中央持续授权内的有效新稿可自动发布；其他稿件交审阅表并沿用具体版本／行批准。发布前核对来源账号、POI、feedbackId、当前未回复状态和准确稿件，claim/check 后才点发布，发布后完整真实回复读回并按 intent artifactHash 提交 provider_readback。correlationMarker 仅在本地绑定该动作。已确认或 unknown 的发布身份不可重放。同步仅使用实际已观察并验证的原评与回复；全部现行门槛成功才整轮归档／清理，保留原忽略项和各自状态的历史事项。

## 自然周经营周报

使用 `smedc-business-analysis` 已有链路：build_query_plan → 官方范围下载 → load_partition_extract → assemble_query_bundle → run_weekly_report → attach_business_advisory 的 prepare/attach。报告必须含 agent 撰写并校验事实锚点的经营建议，不能把事实渲染当完成报告。

build_query_plan 的 `--store-names` 传冻结的准确完整名称列表；官方下载使用这些完整名称作已授权候选范围，load_partition_extract 在聚合前再做精确等值过滤，相似长店名不进入结果。不要把 `--store-name-contains` 当精确授权。超过20店时保持最多2000个完整选择，按20个来源筛选分批请求，消费时仍按全体准确名称过滤；覆盖结果也按所有选定分批完整收集，不能覆盖前一批。默认 range 下载，只有原技能明确选择且部署验证通过时才用 bundle。

周报固定使用业务技能中的关联名称优先匹配、原品项数量保留与餐具收费分列规则；不由企业配置关闭，不复制本机 HTML 替换脚本。

可选 store-groups JSON 为 schemaVersion=1、groups={任意非空组名:[精确店名,...]}，来自中央 groups，不固定要求“大店／小店”。各店只归一个分组；分组不能扩大范围。未分组的已选门店继续纳入，并标未分组。报告 organization 仍来自当前认证账户，展示 company 不充当授权。

沿用上一自然周、环比周、可比同比及既有趋势窗口定义；范围下载受数据权限和coverage约束，不自动补采历史。保留数据缺口、partial 和读取失败的区别。仅通过事实／建议／HTML完整性核验的最终报告可进入邮件阶段；无 Gmail 时本地交付，默认保留最终 HTML。
