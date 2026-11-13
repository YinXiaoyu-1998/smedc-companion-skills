# 宿主 SMTP

DSH 邮件由宿主已配置的 SMTP 发送。由宿主安全设置注入 `SMTP_HOST`、`SMTP_PORT`（默认 STARTTLS 587 或隐式 TLS 465）、`SMTP_SECURE`、`SMTP_USER`、`SMTP_PASS`，Python 不读取任意 .env，不记录密码，不关闭 TLS 验证。SMTP_USER 必须匹配中央已授权发件人；只用冻结的 To，不加抄送或密送。使用实际 `native.smtpReadiness(sender)` 登录验证，记录 email_identity 和 smtp_submission。准备检查不发送邮件。

初始化 native 时提供规范绝对路径 `smtpJournalRoot`，位于专属安装的私有持久目录，目录权限仅本用户可读写，并保留到中央回执完成。所有业务邮件沿用 native.sendEmail(session,intent,mail) 和既有意图、哈希、收件人授权与去重。周报只有验证过的 HTML 附件，新稿使用准确的冻结正文。SMTP helper 在发送前核对该正文或附件的字节哈希，全部收件人被接受后才进入 DATA。

SMTP 最终 250 证明中继接受提交。helper 先原子保存 Message-ID、哈希和状态，再由 native 记录 smtp_accepted；不表示最终邮箱收件。DATA 前服务器明确拒绝可记 request_rejected。中断、超时和不确定返回记录 unknown，恢复先调用 native.reconcileEmail 核对原动作和本地确切接受回执；缺回执时保留 unknown，由用户通过邮件系统核实，不自动重发。SMTP 不要求 IMAP 或 Gmail 已发送读取。使用 [RFC 5321 §4.2.5](https://www.rfc-editor.org/rfc/rfc5321.html#section-4.2.5) 的接收责任语义。

邮件不可用只阻塞邮件相关步骤。真实发送验收须在已授权的隔离任务或正式工作流中进行。SMTP 故障不触发上传、同步或发布重放。
