# 周报驾驶舱与顾客声音

`run_weekly_report.py` 生成固定的驾驶舱页面，详细分析从门店、经营建议、顾客声音和跨店专题进入。首页只填一条有事实支撑的经营判断。先说本周变化，再点出最先要处理或验证的门店和问题。没有可比口径时用本周绝对值，不给缺失数据补零。首页指标和图表由程序生成，经营判断从 advisory JSON 读取。

## 评价取证

仅在周报中使用 SMEDC 已同步的评价。核对官方 MCP 的 `query_store_reviews` 可用且当前账户具备对应评价读取权限。使用同一企业，`storeNames` 为 `prepare` 输出的本期门店完整名称或 `weekly_store_comparison.csv` 中 `current_rows > 0` 的准确门店名单。使用北京时间，`reviewedAtFrom` 为本周开始日加 ` 00:00:00`，`reviewedAtTo` 为本周结束日加 ` 23:59:59`。保持查询范围，按 `page.nextCursor` 继续，直到空指针。超过 100 店时将完整店名分成不重叠批次，逐批读到末页后再开始下一批。每页按顺序保存为 `{"request":实际工具输入,"response":完整返回}`。没有权限、工具不可用或读取未完成时记录原因，在周报交付说明中标明评价覆盖，避免把缺失写成零评价。无正文或无评价时不生成主题。

```bash
python3 scripts/weekly_dashboard.py --report runs/RUN_ID/report.html --output runs/RUN_ID/review-facts.json runs/RUN_ID/review-01.json
```

有多页时按取数顺序传入所有响应。保存原 MCP 响应到专属证据目录。生成的 `review-facts.json` 保留按店合并的相同正文和本轮引用 ID。不要把正文或响应复制到日报、日志摘要或邮件正文。

## 智能体填写的字段

有本期营业数据时，填写 `dashboard_headline`，120 字以内，使用原事实中可核对的金额、变化或经营现象，避免把假设写成结论。

使用评价时，在 `attach_business_advisory.py prepare` 和 `attach` 都传同一个 `--review-facts runs/RUN_ID/review-facts.json`。逐店阅读完整正文组，再填写生成的 `customer_voice`。保留 `facts_digest` 和每个有正文的门店。企业 `overview` 提炼值得优先验证的经营问题；各店 `headline` 给出一句判断。各店择 0–4 个有决策价值的主题，可只写判断而不给缺乏依据的主题。主题提炼具体菜品、服务环节或场景，将值得保持的做法和待核查的问题说清。重复文字不当成独立顾客；纯评分不用来推导具体主题。

每个主题写 `title`、简短 `cloud_label`、`tone`（`keep` 或 `check`）、`observation`、`judgment`、`action` 和 1–4 个 `evidence`。例如 `{"review_id":"R1","excerpt":"实际评论中的简短逐字片段"}`。每个片段 1–120 字，避开姓名、联系方式及订单号等个人信息。评价只作体验线索，和经营变化并列核查；个别投诉先现场确认，跟进动作要明确到品项、流程、班次或角色。不要用关键词占比替代判断。最终 HTML 只嵌入经过校验的主题和引用片段，保留完整评价于本机证据目录。
