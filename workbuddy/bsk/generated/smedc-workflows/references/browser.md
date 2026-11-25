# 浏览器选择与恢复（browser-skill 特化）

本 profile 只使用宿主 `browser-skill` 的 `bsk` CLI，完整指引见 `workbuddy/references/browser-skill.md`。
CDP Proxy / `web-access` 通道的规则在这里**不适用**。

1. 一次性配置是 CLI + 扩展 + 配对 + `bsk doctor` 全绿；美团登录态走同 profile cookie jar，
   持久有效。每轮只需确认 daemon 在跑，agent 可自行拉起，无需员工每次授权。
2. 复用同一 Agent Window 会话完成查询、导出、下载清单与文件落地；换会话前先核对已发
   导出是否仍在生成，保留 runId、日期窗口、导出 ID 和重试计数。
3. daemon 或扩展不可用时保存精确阻塞与待续范围，只阻塞相关来源阶段；其他已获授权且
   可独立验证的阶段继续，整轮按 partial 收尾。
4. 不搬运 Cookie、不改 UA、不猜接口、不绕过 borrow 确认或扩展的 Automation 设置。

本文件由 `workbuddy/bsk/build.py` 生成，请勿手工编辑。
