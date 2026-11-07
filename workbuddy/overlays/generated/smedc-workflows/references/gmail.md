> **WorkBuddy 宿主优先级**：本文件涉及浏览器选择、登录态、保存框、下载等待、
> 宿主工具与定时任务的段落，一律以 `workbuddy/HOST_MAP.md` 与 `workbuddy/WORKFLOWS.md`
> 以及 SKILL.md 顶部的「WorkBuddy 宿主适配」章节为准。上游专有接口名已替换；业务筛选、
> 原件校验、证据与清理门槛不变。此文件由 `build_overlays.py` 生成，请勿手工编辑。

# 原生邮件连接器（本宿主不可用） 发送与未知结果核对

首版只用固定的宿主原生 原生邮件连接器（本宿主不可用） 工具命名空间，不选其他服务器同名后缀或 SMTP。原生邮件身份工具（本宿主不可用） 当前 email_address/emailAddress/email 必须与中央 allowedSender 完全一致；凭据留连接器。收件人只用快照显式列表，不加 cc/bcc。

冻结 email intent 的 purpose、storeNames/window、recipients、sender、deliveryVersion；新稿再加每个 source/feedbackId/recipient。artifactHash 是准确最终 HTML／新稿通知正文的 UTF-8 SHA256，correlationMarker 是稳定可查询标记。正文、发件人或任务 ID 改变不改变中央去重身份。

`native.sendEmail(session,intent,mail)` 在当前授权及持久 intent 后发一次，mail 含 artifactHash/subject/原生 MIME payload，subject 不接受换行并附 marker。正文先本地核对 SHA。周报唯一附件为最终 .html，MIME=text/html，content_disposition=attachment；正文和主题说明报告期、范围及缺口，不附原件、配置、中间事实或未完成报告。普通自动发送使用现行持续授权，不要求 manual_resolution 或逐封人工批准。 邮件登记另检查 `email_identity` 和 `sent_mail_lookup` 的 24 小时有效期。遇到中央登记拒绝且这两项已过期或缺失，适配器用实际 原生邮件连接器（本宿主不可用） 账号和只读已发送查询补查，合并登记并读回后，只重试同一中央登记一次。这个重试发生在 原生邮件连接器（本宿主不可用） 派发前；已派发或结果未知继续按原标记核对。

## 明确发送回执

原生 原生发信（本宿主不可用） 成功返回的实际 id（或同义 message_id/message.id）是明确发送回执，先持久保存。随后 原生邮件读回（本宿主不可用） 读取这个确切消息 ID：

- 使用实际返回的 messages/thread.messages/emails 或单消息对象；id/message_id 必须匹配原回执。
- 发件／收件取实际 headers 的 From/To/Cc/Bcc 或规范 from/to/cc/bcc（字符串或 email 地址对象）；完整范围须一致，不能把空数组误判为有抄送，也不能忽略真实抄送。
- Subject 须与本次准确主题及 marker 一致。有 SENT 标签时核对；没有标签时，明确 原生发信（本宿主不可用） 回执仍可绑定这条消息。DRAFT 与发送证据冲突则保持 unknown。
- 附件取实际 attachments 或返回 MIME parts 的 filename、attachment_id、size/byte_size/body.size、mime_type。与已发送准确文件名、数量、可见大小和类型核对；无大小时至少有实际附件标识。不得虚构 rawMime 或假称已取得远端字节。

若连接器实际返回完整 body.content/base64_url_content/data，可进一步解码并核对 provider 字节 SHA；缺字节不使有明确发送回执且身份／附件读回一致的正常邮件必然失败。中央 provider_readback 绑定 identityHash、已知 outgoing artifactHash、marker、providerReceiptId、observedAt/outcome=sent。这里的 artifactHash 是发送前真实原件哈希；没有远端字节时不声称它是远端 MIME 哈希。本地证据另记 providerBytesVerified、实际身份／附件及验证方式，审计为客户端 readback。

## 结果未知

超时／响应丢失不重发。`native.reconcileEmail(session,intent,action,continuation)` 先从中央 get 原动作的完整身份、artifactHash 与 marker，再用 in:sent＋原 marker 查询。逐页核对，保存 continuation 的 pageToken/matchedIds，完整结束后只接受唯一精确匹配。

未知恢复没有本次明确发送回执的绑定，单凭相同主题、文件名、摘要或预览不能确认原 artifact。必须有实际可取的原 body／附件字节匹配哈希及准确身份；若只见附件标识、内容截断或能力不足，继续 unknown 并列具体证据缺口，可由用户明确的人工核对解决。不能合成 MIME 哈希，不能换 marker/deliveryVersion 重发。零命中也不证明未执行。

需要原附件时，仅对 原生附件读取（本宿主不可用）_supported=true 的实际附件用原生 原生附件读取（本宿主不可用），使用 parent id 和完整 attachment_id／准确 filename；不猜 ID。拿不到完整原字节就如实保留未知。开发只使用合成工具结果，真实 原生邮件连接器（本宿主不可用） 字段／发送验收留到后续明确授权的运行；工具发现不是发信测试授权。

原生邮件连接器（本宿主不可用） 失败只阻塞邮件阶段，仍保留本地最终报告及独立采集／审阅结果。通知保持每评价×收件人去重；已确认、未知、失败和待通知分开，不把邮件故障变成重复上传或发布。

claim 返回 partialOverlap=true 时，只表示批次内已有部分评价×收件人身份被占用；不能将整个批次算作已通知。先按 conflictActionIds 核对原回执／未知项，再仅为准确未占用的新稿身份准备新的受控批次。部分已确认不让其他项跟着成功，也不重发整封原批次。
