# 周报驾驶舱与顾客声音

`run_weekly_report.py` 生成固定的驾驶舱页面，详细分析从门店、经营建议、顾客声音和跨店专题进入。首页只填一条有事实支撑的经营判断。先说本周变化，再点出最先要处理或验证的门店和问题。没有可比口径时用本周绝对值，不给缺失数据补零。首页指标和图表由程序生成，经营判断从 advisory JSON 读取。

## 固定模板与补充事实

正式周报和定时周报共用 `assets/weekly` 中的 v4 模板。首页六张图、侧栏与下探页由固定结构生成。用户有同组织、同店、同周的授权订单和可核验品类汇总时，可在渲染命令加 `--dashboard-facts`。输入为排除原始订单号、个人信息和正文的汇总 JSON，`context` 包含 `organization_name`、排序后的 `store_names`，以及与报告完全一致的 `windows.current`、`windows.previous`（`start/end`）。仅传已用官方读取结果核验的可选 `orders`（按用餐人数）、`takeaway`（按平台）或 `products`（按品项和渠道）汇总。正式定时任务只消费其现有授权覆盖的事实；明细未覆盖时仍可从相同入口看营业汇总。

## 堂食客流与估算翻台

- **取数。** 给周报同企业、同门店筛选额外读取店内订单明细覆盖，保存成功回读为 `coverage_in_store_orders.json`。精确店名超过 20 家时按原周报分批覆盖流程收集。计划只下载本周授权订单，营业分组表沿用原抽取。店内订单无权限或无覆盖时记录范围，继续生成可用的翻台；覆盖读取错误保留证据，下载失败沿用标准恢复流程。使用可选 `--dashboard-facts` 的人数分组时也排除已识别的异常订单。
- **核查人数。** 订单须为「已结账」且用餐方式为「堂食」。在物化前按店按日查看人数分布和明显跳升，优先核对远超通常桌型的单笔登记。对照桌牌、桌型、金额、同桌订单与经营记录，尤其警惕把 1,000 多人录在一张桌上的情况。程序会暂排除单笔登记达到 1,000 人、无有效人数或冲突的记录。其他已核对的异常可在本轮私有 JSON 数组中登记，每条含 `store_name`、`business_date`（YYYY-MM-DD）、`order_id`、`reason`，传给 `load_partition_extract.py --headcount-exclusions 文件`。保留原登记和核查依据，勿猜填人数或将异常高点解释为团体客。
- **核对交付。** `weekly_dine_in_by_day.csv` 与 `weekly_dine_in_totals.csv` 提供全店及各店结果，含有效覆盖和排除笔数。翻台只汇总营业表堂食的桌台使用次数，每店每日的配置桌数只取一次。周和跨店汇总先加总分子、分母再相除。缺日按实际覆盖显示；缺失项留空。核对首页和门店页都显示对应的周指标及逐日明细。异常人数另行说明；报告中只保留聚合数。饱和度判断需要实际可用桌台、高峰占用或等位证据。

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
