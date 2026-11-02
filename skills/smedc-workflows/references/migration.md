# 三任务迁移与换机

只在用户请求的实际迁移范围中读取私有文件。开发／发布不改现有任务，不发信／回复，不跑真实数据回填。所有迁移包、真实配置、收件人、品牌资料、回执和详细证据留私有目录，不入 Git。

## 显式来源与字段预览

先读实际三个任务定义的完整 TOML，保留实际 RRULE、模型、推理设置和时区作为一次性宿主重建输入；新机不复用旧 taskId、cwd、project ID 或机器路径。读 prompt 中明确引用的 policy/task/groups/state/ledger/receipt/lock 文件；继续解析这些文件的明确引用，直到必要依赖闭合。不要扫描 raw_exports、全部报告、聊天或历史 memory；缺项记待核对。

agent 在私有目录生成迁移描述 JSON，用户只审阅业务差异，不填写 JSON。用 `workflow.py migration --input DESCRIPTION --output BUNDLE` 生成可提交中央的 manifest、有界 pages、全链摘要，以及仅本地的字段来源／证据清单。

描述字段：integration、targetVersion、workflows、sources。

- workflows 为目标稳定 workflowId、严格中央 configuration、authorizations 和 taskSource（来源 id）。授权是从现行明确授权核对出的迁移草案，不从 installed 技能或安装操作推断。
- sources 每项有随机／通用 `id`、`kind`、规范绝对 path、可选 expectedSha256、所属 workflowId。kind 只允许 task、settings、policy、groups、receipts、control、evidence。任一文件变化使来源摘要变化，不覆盖既有已确认预览。
- task：完整真实 TOML，固定 observedAt。references 列出所需来源 id；promptDecisions 为 prompt 全部非空规则的精确 excerpt 及去向。不得只把 prompt 当完整配置。activeRun=true 立即阻塞，旧锁不能按年龄被夺取。
- settings/groups：fields 对每一个顶层字段声明 source JSON pointer 和 destination。central 要求 target JSON pointer 及与目标完全相同的值；仅允许 identity、named_groups（旧 groups 字典→中央具名数组）、recipient_list、review_policy:字段名 和 ignored_review_identities 转换。四个已知 policy 字段各自核对精确语义，再映射到同一 executionPolicy 预设；忽略身份转换须显式 sourceAccountRef，唯一核对中央来源映射。local_evidence/obsolete 必须在预览说明原因；needs_review 阻塞。未处理字段、两份来源不一致都阻塞，不能默认后一份覆盖。
- policy：decisions 对每条非标题规则给精确 excerpt、destination。central 还给 target/value，核对目标。未覆盖、无法解释的例外、旧“映射外都闭店”规则必须待核对；不将自然语言执行为指令或服务器任意 prompt。
- receipts：recordsPointer 指向完整列表。每项保留稳定 legacyKey（或 legacyKeyHash）、规范 intent、receipt。已知旧 JSON 结构可用 recordFields 的明确 JSON pointer 映射，或 recordTemplate 闭合模板：$pointer 选原字段、$target 选已核对目标配置、$hash 计算摘要、$actionId 生成稳定非个人动作 ID、$map 将明确旧状态映射为已核对的状态枚举；没有脚本／表达式执行。完整列表逐项转换，不按正文猜状态。不可按文件名或请求已接受推断成功。只提交限定的身份、时间、哈希、状态和 provider/job 回执，正文与快照不进入中央。
- control/evidence：用 recoveryLists 对 items/evidenceItems/resolvedItems/resolvedReviewIssues/waivedItems 的完整数组逐项选择同样的闭合模板，生成类型化 recoveryItems；非空旧数组未声明就阻塞。保留未解决、waived、归档和失败原件的精确证据指针／SHA；缺本地证据保持明确未恢复。unknown 必须绑定原 intent 和 unknown receipt，不能把 waived、已清理或缺文件都翻成成功。

每日保留五类选择、来源集团品牌／门店映射、settled_only 选择依据、逐类进度与已发布任务；旧来源口径无法证明的保持 unknown。评价保留多 POI、采集与回复白名单分离、当前日期窗口、品牌／语气／图形文字规则、新旧保护、完整同步读回、通知／发布持久去重、严格整轮清理和既有例外。周报保留准确分组、比较口径、允许发件身份和所有收件人、最终 HTML、部分数据标记及邮件去重。已识别四项通用规则映射为 executionPolicy={id:verified-review-operations,version:1}，忽略记录映射为 ignoredReviewIdentities（有意排除，不是完成动作）。不支持或冲突的例外阻塞，不能只留旧机文件后宣称新机可恢复。

明确排除的来源店铺使用现有 integration.exclusions，每项保留 product/accountRef/channel、稳定来源 ID（有则优先）或精确全名及 reason；真实名单只保存企业配置。已有明确排除决定按原记录迁入，不因迁移再次要求选择；旧“所有未映射均闭店”规则需由用户确认改为有限排除名单＋未知店 needs_configuration。当前会话已有确认即复用，在迁移预览中记录依据，不重复确认。排除不等于闭店、不删除历史，不自动扩展到其他账号或渠道；已映射但未被任务选择也不等于闭店。未知来源保留待配置，不能暗中扩容或自动排除。

报表的关联名称优先、原品项数量与餐具收费分列属于官方固定实现。升级时逐目录合并遗漏的通用能力并验证，不迁成企业开关，也不以保留本机渲染补丁代替官方实现。日期、分组、门店、收件人与授权仍属企业设置。

## 不支持的旧容器：私有规范投影

遇到每日 datasets/reports/files 字典、周报单个回执对象或根数组 control 时，agent 在私有目录准备规范元数据投影：回执用完整列表供 recordsPointer/recordTemplate 读取，控制项用对象及显式 recoveryLists。只转换容器和已核实别名，不新增通用转换器，不让用户手工填写 JSON。

- 保留全部选中原文件的完整 SHA-256；不兼容容器原件仍以 evidence 来源纳入 sources，投影另列来源及自身哈希。真实 taskSource、完整任务定义和全部 prompt/policy 规则仍按原有类型声明实际去向，不能用 evidence 哈希代替。
- 每个投影字段留存原来源 id／完整哈希、精确 JSON pointer、原值和别名／转换依据及目标字段。单对象包装、字典展开、to 字符串／数组、messageId/gmailMessageId 等解释须逐格式明确核对；冲突保留阻塞，不能默认后一项覆盖。数组下标或文件名不能充当持久动作身份。
- 独立重读原文件逐一验证全部 pointer／值绑定与别名，复核每个容器的完整数量及重复观测处置，再核对投影、严格目标 schema 和生成 bundle 的全部记录／规则去向。CLI 不自动证明投影与原件的 pointer 关联；原文件作为 evidence 纳入哈希也不等于语义闭合。
- 缺失身份、范围、原业务哈希、sender、终态或证明均明确保留 unknown／待核对，不能从当前设置、顶层完成标签或其他哈希补造。投影生成成功不代表完整迁移；用户审阅实际业务差异，必要历史、未知项和最终冻结来源核对齐全后才继续导入与切换。

## 分批导入及完整读回

每请求最多100条／256KiB，静态配置不超过1MiB。历史没有100条总上限；描述读取单文件上限32MiB，超限明确拆为多个来源，不截断。初始 manifest 含第0批，其余 pages 顺序 append；来源摘要同时绑定原文件哈希、明确字段解释及规范记录摘要，修正解释后必须新预览。每批 chunkHash 和全链 chunksDigest 使用与共享 domain 相同的递归排序键 canonical JSON SHA256，重复导入以 sourceSnapshotHash＋targetVersion 幂等。

`native.migrate` 调 migration_preview、逐页 migration_append、migration_seal。原子保存每次 migrationId/version/摘要，失败恢复同一流；封口后不再追加。用户核对字段去向、未解决项和封口后的 confirmationDigest，再 `native.advanceMigration` 分别 validated 和 imported；每调用只处理一批，complete=false 时继续同阶段，不能提前切宿主。

`native.verifyMigrationReadback` 使用 migration_get 分页读取全部批次，逐页哈希／顺序／计数／全链核对并保存到本机。检查全部配置、授权、历史身份及必要例外都能从中央读回，而不是只看第一页或 imported 标签。导入保持中央 paused，不激活旧企业 orderScope-required，不更改现有任务。

## 切换及旧机丢失

旧机可用：先用原生工具暂停旧实际任务，读回状态；等待已发动作核验、处理未知并释放租约。新机读取中央现有企业／门店／邮箱／分组／授权，只完成官方登录、两个美团入口、Gmail、目录和宿主能力检查；不要求重新配置业务。

新机通过 prepare_takeover 读取精确旧安装／epoch／lease／unknown 列表；用户核对后 takeover，中央原子撤销旧资格。安装新任务为 paused，回读 schedule/model/timezone/notification、record_host，再按已确认范围启用中央／宿主；更新迁移 host_switched。首次受控实际运行通过后记录 firstRunVerification，最后 verified。未达到对应阶段不显示已完成换机。

旧机不可用：明确撤销旧资格，等旧租约到期并核对未知动作，不能自动抢占。新机从中央恢复已确认配置与回执；本地原件缺失显示 missing_local_evidence，只重取可核对的未完成来源。不以找不到旧文件为理由重发已确认／未知邮件或回复。

失败保留原配置、任务和证据；回退必须先撤销新资格、恢复旧资格并处理未知动作，不能让两套任务同时启用。旧完成台账对应稳定企业工作流实例，不对应 automationId。未完整恢复必要例外和全部回执前，保留具体阻塞，不能宣称完整迁移。

## 非动作工作和全新本机恢复

recoveryItems 与 completedActions 分离，每项只含 itemId、business/evidence、open/waived/resolved、固定 stage、关闭的 scope（dataset/reviews/report/unknown_scope）、可选 evidenceRef/evidenceHash 和 resolutionReason。waived/resolved 必须保留明确原因；scope 不明就 unknown_scope，不能猜日期／门店，不能伪造成功动作。evidenceRef 是无路径的短 ID，详细原件留本机或受控文件迁移。三类数组合计每批100条／256KiB；旧批没有 recoveryItems 字段时保持字段缺省以保护旧摘要，不补空数组。

新机没有本地 migrationId 时，调用 `native.restoreMachine(selector,saveState,savePage)`：实时读取当前配置，分页 get_workflow_status 的 migrations/nextMigrationCursor，通过 manifest 全部成员发现共享迁移，再逐批 migration_get，核对数量、顺序、哈希与全链。pendingActions/nextActionCursor 分页后 get 取原 identity/identityHash/artifactHash/correlationMarker/receipt，不能重新生成 marker 或靠新 task ID 重发。

saveState / savePage 都由实际 native.saveLocal 写本机专属目录，例如：

```javascript
const savePage = async (page) => {
  const key =
    page.kind === "migration_chunk"
      ? "migration-" + page.migrationId + "-" + page.sequence
      : page.kind === "current_configuration"
        ? "current-" + page.workflowId
        : "pending-" + page.workflowId + "-" + page.index;
  const path = recoveryDir + "/" + key + ".json";
  await native.saveLocal(path, page);
  return path;
};
const state = await native.restoreMachine(
  selector,
  (value) => native.saveLocal(statePath, value),
  savePage,
);
```

完整回执／恢复项目按批保存，紧凑状态只存计数和页引用；不会每轮扫描全部报告。当前配置与最近确认安装快照优先于历史 manifest；历史快照只补缺失的日程输入，旧机器的 taskId 永远不作为新机 update 目标。新宿主 journal 从空或本机自己的已确认登记开始。restorationComplete 只表示元数据读回完成，readyForActivation 仍为 false；未登录、缺本地原件、未知动作和开放工作继续准确显示，绝不自动回填。

原始旧任务尚未采用中央租约；开发／安装都不得擅自暂停它们。先完成预检与 PAUSED 准备，最后在用户确认切换窗口核实旧任务暂停或旧设备退役。只撤销云端登记不能保证旧原始脚本停下。

预检及早期暂停导入可以在旧任务仍运行时准备，但这不是最终移交快照。旧任务真正暂停／旧设备退役、最后在途动作核对后，必须重新核对全部来源哈希及最后的通知／发布／同步回执；有晚到变化则完成相应新预览、增量导入和全量读回，再启用。无法证明移交快照覆盖最后活动时，明确保留对应未知范围并阻塞相关邮件／发布，不能用旧封口清单冒充最新完成台账。
