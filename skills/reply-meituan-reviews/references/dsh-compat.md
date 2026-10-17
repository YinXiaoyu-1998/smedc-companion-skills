# DeepSeek Harness（dsh）适配说明

> **本文档专门针对 DeepSeek Harness（dsh）运行环境。**
> 它只记录 dsh + 浏览器工具下的**落地写法与已知坑**，不改变 `SKILL.md` 的任何流程、筛选规则、审核边界或发布授权要求。
> 使用 Codex / Claude Code / 其他运行环境时可以直接忽略本文；本文与 `SKILL.md` 冲突时，一律以 `SKILL.md` 为准。

## 0. 能力前提

dsh 没有 Codex 的 `iab`、`cua_repl`、`tab.playwright`。可用的浏览器能力来自以下任意一种，语义等价：

| SKILL.md 中的 Codex 接口 | dsh 等价能力 |
| --- | --- |
| `iab`（内置浏览器标签） | BrowserSkill 插件的 `bsk_session` / `bsk_tabs`（Agent Window，复用已登录会话） |
| `tab.playwright` | `bsk_page` / `bsk_interact` |
| `cua_repl` 执行脚本 | `bsk_inspect`（evaluate 类动作），或 `bsk` CLI |
| 语义树 / 无障碍树 | `bsk_inspect`（observe / snapshot） |
| 截图 | `bsk_page` 的 screenshot 动作 |

没装插件时直接用 `bsk` CLI（`bsk session start` / `navigate` / `evaluate` / `session stop`），与本表等价；两者共用同一个 daemon。

## 1. 美团经营宝是 iframe 页面（最关键）

- 入口页 `/meishi/?cate=6103#...` 的正文位于**同源 iframe** `#iframeContainer`，内容地址是 `https://ecom.meituan.com/emis/evaluation/poi`。
- 后果一：`observe` / `snapshot` 在这个页面上会 **30s RPC 超时**（页面过重），重试也无法改善，不要反复试。
- 后果二：CSS 选择器与 `@eN` ref **不跨帧**，在主文档里查不到门店选择器、评价卡片。
- 后果三：直接打开 iframe 地址会禁用门店切换（页面提示"门店选择失败：页面不要脱离框架使用"），只能读当前门店。
- 可行配方：用 evaluate 取同源 frame 的 `contentDocument`，在内部查询与点击。

```js
const d = document.querySelector('#iframeContainer').contentDocument;
// 读：d.querySelectorAll(...)    点：el.click()
```

## 2. 定位配方（实测可用）

| 目标 | 定位方式 |
| --- | --- |
| 渠道页签 | `button.tabs_tabItem_yRYSi`，按文字前缀"美团评价"/"点评评价"区分 |
| 筛选组 | 先按行首文字（"是否回复"/"评价时间"/"评价星级"…）找到行，再在行内按"未回复"/"全部"精确匹配 |
| 门店选择触发器 | `.index-module_container_Oy7Uq`（点击后弹窗渲染在**父文档**，不在 iframe 内） |
| 门店弹窗 | 父文档中的表格行，按门店名精确匹配后点 radio，再点"确定" |
| 评价卡片 | `.index-module_container_yXIo8` |
| 客户名 / 时间 | `[class*=username]` / `[class*=time]` |
| 总星级 | `[class*=starsContainer] img`，按 src 含 `full`/`half`/`empty` 累加 |
| 正文 | `[class*=content_nM2ZO]`（去掉末尾"投诉 / 回复 / 展开 / 收起"残留） |
| 分页 | `.mtd-pagination-pager li[title="N"] button` |

读数注意：切换渠道后筛选会**重置**，每次都要重新设"未回复 + 全部"再记总数；"共 N 条评价"在页面上会出现多次（另一渠道的缓存值），以当前列表上方那个为准。

## 3. 点击安全红线（在 SKILL.md 的"不要点广告 / 开通 / 开始体验"之外补充）

- 只点击**白名单控件**：页签、筛选按钮、分页、门店选项与"确定"、弹窗关闭"×"。
- 严禁点击：`投诉`（会真的发起投诉）、`举报`、`去报名`、`开始体验`、任何营销位。
- 使用坐标点击前，先把目标元素的祖先链过一遍；**若祖先容器文字含"投诉 / 回复 / 发送"则放弃该坐标**。一次误触就会在卡片上留下"投诉失败 / 投诉成功"痕迹。
- 第二阶段发布同理：只点目标卡片内的"回复"，填入获批正文后点一次"发送"，其余一律不碰。

## 4. 同名门店风险

同一家实体店可能存在多条 POI，例如：

- `麦家鲜羊肉（武圣路店）` — POI 1024500978936273
- `麦家小馆鲜羊肉烧烤·海鲜·精酿·西北名吃（武圣路店）` — POI 1024080006230699

用户说"武圣路店"时可能指其中任意一条。**切店后必须回读门店选择器文字确认**；把实际使用的 POI ID 记进交付说明；两条都符合且用户未指明时先问。

## 5. 表格生成

dsh 没有 Codex 的 Spreadsheets 技能，用 `office-xlsx` 技能或直接 openpyxl：

- 日期写入真 `datetime`，单元格格式 `yyyy-mm-dd hh:mm`（不要写文本）。
- 换行用 `Alignment(wrap_text=True)`，显式设置列宽，`freeze_panes='A2'`，并加 `auto_filter`。
- 生成后重开文件校验：五列顺序、行数 = 去重记录数、日期是 datetime、非回复列无空值。

## 6. 交付前自检

1. 两个渠道都设过"未回复 + 全部"，并各自记录总数；
2. 每页读完、分页翻到底、长评已展开；
3. 总评来自星标显示而非小项均值；日期已补年份；
4. 文件能打开、行数对得上、无占位文本；
5. 全程未点"回复 / 发送"。
