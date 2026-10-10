# 顾问方法参考与取舍

核查日期：2026-10-11。以下是经过查看原文的参考来源。本 skill 的顾问指引是结合现有事实口径重新编写的；没有复制外部技能包、引入外部 API 或安装依赖。

| 来源 | 值得借鉴 | 本 skill 的适配与取舍 |
|---|---|---|
| [阿里云官方 Quick BI SmartQ](https://github.com/aliyun/alibabacloud-aiops-skills/blob/master/skills/analyticscomputing/quickbi/alibabacloud-quickbi-smartq/SKILL.md)；[洞察模块](https://github.com/aliyun/alibabacloud-aiops-skills/blob/master/skills/analyticscomputing/quickbi/alibabacloud-quickbi-smartq/references/insight/module-data-insight.md)；[分析框架匹配](https://github.com/aliyun/alibabacloud-aiops-skills/blob/master/skills/analyticscomputing/quickbi/alibabacloud-quickbi-smartq/references/dashboard/module-dashboard.md) | 将数据获取、解释与报告区分；依据实际指标、维度及关联关系选择分析框架 | 采用事实→综合判断→报告的流程。继续由当前智能体分析 SMEDC 事实；不采用 Quick BI 外部上传、试用注册、凭证和远程解释端点，也不假定有足够数据做 RFM 等分析 |
| [Mercury `menu-engineer` 原始 skill](https://github.com/cosmicstack-labs/mercury-agent-skills/blob/main/categories/shop-restaurant/menu-engineer/SKILL.md)；国内发现入口 [tool.lu](https://tool.lu/skill/s/2RK) | 同时看受欢迎程度与单品贡献，按问题给出可测试的动作；持续复盘 | 现有数据缺成本，因此只采用销售结构与小范围试验视角。排除固定涨价幅度、固定食材成本比例、利润提升承诺、无证据的价格弹性和菜单位置效果数字。该技能是社区贡献，市场收录不等于方法已验证 |
| [中文 `yongge-restaurant-master` 原始 skill](https://github.com/Bruce-N-Meow/yongge-restaurant-master/blob/main/SKILL.md) | 根据经营处境选择诊断问题；先拆经营机制，再讨论行动 | 仅借鉴问题导向与多因素核查；不采用人格模仿、辱骂、必然成败判断、固定行业阈值，以及依赖租金、成本、竞品或商圈信息的盈亏处方 |
| 当前安装的 Data Analytics `metric-diagnostics` | 区分指标重现、贡献分解、原因假设与决策；检查组合效应、反证和残差 | 将这些分析质量要求改写为 SMEDC 门店/渠道/餐段/菜品的检查，不继承其其他连接器、消息发送、自动化或数据仓库访问流程 |

国内检索也覆盖 [腾讯 SkillHub](https://skillhub.cloud.tencent.com/skills/find) 和 [阿里云 Agent 服务目录](https://agentcatalog.aliyun.com/skills?orderBy=install)。腾讯页面的公开抓取存在加载失败，不能据此断言没有相关技能，也不能把市场中的社区技能称为腾讯官方顾问方法。公开资料中找到的参考还不足以直接承担本项目的整套餐饮顾问工作，所以采用可核查的方法片段，自行约束证据、口径和行动边界。

对后续新增参考，同样检查原作者、原文、数据前提和不可靠的固定数字。引用来源不代表认可其全部结论；如果将来复制源码或正文，须另行核查并保留许可证及归属。日常生成企业报告无需重新搜索技能市场，也不将方法来源包装成企业事实或行业基准。
