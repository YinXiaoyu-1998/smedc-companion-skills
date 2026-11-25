# WorkBuddy 网页操作手册

本手册适用于本机 BrowserSkill 的 `bsk` CLI、Chrome 扩展和 Agent Window。业务筛选、证据、
原件校验及清理遵循相应的美团 Skill 和中央冻结快照。

## 1. 运行条件

使用本机连接和自己的 Agent Window。扩展复用所选 Chrome 实例的登录态。登录、验证码与重新认证
由员工在美团页面完成。远程连接的文件上传和下载受 BrowserSkill 限制，本手册使用本机下载目录。

## 2. 每轮检查

按[上手指南](../GETTING_STARTED.md)配置 CLI、扩展和本地连接。每轮确认 daemon、扩展、
登录态以及来源账号、品牌、门店和报表日期。WorkBuddy 如果回收了 daemon，先确认没有正在启动的
后台任务，再用宿主管理的后台任务运行 `BSK_AUTO_START=0 bsk daemon start --foreground`，
另一次调用复查 `BSK_AUTO_START=0 bsk status --json`。同一轮保持相同的 `BSK_HOME`。
连接不可用或登录过期时保留待续范围并报告来源阶段 blocked。

## 3. CLI 语法

以安装版本的 `bsk <cmd> --help` 为准。已核实的 CLI 接收 `navigate` 的位置 URL 和
`evaluate` 的位置表达式。查看当前控制状态用 `cooperate sync`、`snapshot` 和 `observe`。
保留已核实的浏览器实例 ID、session ID 与上下文。宿主 shell 若不继承 PATH，使用 CLI 完整路径，
或在每次调用里将其所在目录加入 PATH。

## 4. 会话与观察

```bash
export BSK_AUTO_START=0
bsk status --json
bsk browsers --json
bsk doctor
bsk session start --browser "$INSTANCE_ID" --no-focus --json
bsk navigate --session "$SID" "https://pos.meituan.com/web/operation/main#/" \
  --wait-until domcontentloaded --timeout 45s --json
bsk cooperate sync --session "$SID" --policy target --json
bsk snapshot --session "$SID" --max-tokens 3000 --json
```

用 `browsers` 输出填写 `INSTANCE_ID`，以 `session start` 输出填写 `SID`。导航或人工
输入后重新同步，使用本次返回的 `context_id` 和顶层 `observation_id`。
遇到错误先检查 JSON 的工具结果。收尾用 `bsk session stop "$SID" --json`。

## 5. 确认报表 iframe

外层美团 SPA 可能只显示导航和通知。进入报表后读取报表标题、筛选与结果列，刷新 BrowserSkill
快照取得当前控件的 `@eN` ref。CSS 选择器直接传给 CLI 时通常只匹配顶层文档。需要定位同源报表
iframe 时，通过只读检查核实其实际 `contentDocument.location.href`、报表容器和目标控件。
页面导航成功以后还要等待报表自身就绪。

## 6. 选定触发方式并验证原件

**每个导出或下载动作只触发一次。** 先核对报表、实际筛选和操作目标，记录申请时间及下载目录
当下的候选文件。异步导出需等本次任务完成，再处理相应行的下载控件。点击后先观察任务、浏览器
下载列表或本地文件。动作结果不明时保留待续，避免重复生成任务。

- **美团「自助营业取数」iframe**。真实采集中该报表的 VOM 缺少顶层坐标，`bsk download`、
  `click` 和 `scroll-to` 均返回 `target_covered` 或 `element_not_visible`。对此报表直接使用
  下方的 `evaluate --expect` 路径。
- **可按几何坐标点选并确认直出的目标**。先同步取得 `CTX` 与 `OBS`，调用
  `bsk download "$REF" --out "$DEST" --session "$SID" --context "$CTX" --observation "$OBS" --timeout 2m --json`。
  命令包含点击。遇 `download_path_mismatch` 先检查浏览器下载列表和实际文件路径。
- **只提交异步任务的按钮**。根据已核实的控件触发方式提交一次，记录任务标识、申请时间和范围。
  在下载清单定位这一行并等待生成完成，随后针对该行的实际控件选择下载方式。

### iframe 的事件触发路径

1. 只读检查已筛选的报表，取得实际 iframe 完整 URL（含路径、查询和 hash），唯一报表容器的 CSS
   选择器，容器内唯一控件的 CSS 选择器、按钮文本和对应的新鲜 `@eN`。使用从当前页面确认的
   值，避免猜测位置或使用宽泛的 `button`。多个候选时先缩小范围。
2. 从已安装 Skill 目录运行如下命令。样例读取同一 Agent Window 内的一个精确报表 iframe，
   并在该报表中查找已核实的控件。`--expect` 用当前 ref 和按钮文本做额外核对。

   ```bash
   (
     set -e
     export BSK_AUTO_START=0
     : "${SID:?填写当前会话 ID}" "${REF:?填写当前快照的控件 ref}"
     : "${FRAME_URL:?填写实际 iframe URL}" "${REPORT_SELECTOR:?填写唯一报表容器选择器}"
     : "${CONTROL_SELECTOR:?填写容器内唯一控件选择器}" "${BUTTON_LABEL:?填写控件可见文本}"
     CTX=$(bsk cooperate sync --session "$SID" --policy target --json \
       | python3 -c 'import json,sys; print(json.load(sys.stdin)["context_id"])')
     EXPECT=$(python3 -c 'import json,sys; print(json.dumps([dict(target=sys.argv[1], field="text", equals=sys.argv[2])]))' \
       "$REF" "$BUTTON_LABEL")
     EXPR=$(python3 - "$FRAME_URL" "$REPORT_SELECTOR" "$CONTROL_SELECTOR" "$BUTTON_LABEL" <<'PY'
   import json
   import sys
   from pathlib import Path

   keys = ("frameUrl", "reportSelector", "controlSelector", "label")
   arguments = dict(zip(keys, sys.argv[1:]))
   script = Path("workbuddy/scripts/meituan-iframe-export.js").read_text(encoding="utf-8")
   print(f"({script})({json.dumps(arguments)})")
   PY
     )
     bsk evaluate --session "$SID" "$EXPR" --context "$CTX" --expect "$EXPECT" --json
   )
   ```

   `dispatched: false` 表示定位或状态检查失败。重新读取报表和控件后再决定下一步。
   `dispatched: true` 表示事件已派发，随后用页面上的新任务、完成状态或匹配的新下载
   确认效果。连接中断、体检异常或没有观察到结果时，先调查已有任务和文件。

3. 美团可能把文件保留为 `~/Downloads/.com.google.Chrome.*`。只处理本次操作之后出现且能与
   本次报表和范围对应的文件，等大小稳定后校验。多个候选无法归属时先保留现场。XLSX 检查
   ZIP CRC、OOXML 工作簿结构及工作表内容，再按业务 Skill 核对日期、门店、筛选范围与数据行。
   ZIP 类原件按相应业务 Skill 检查成员、路径及完整性。报表与范围不符的文件保留待核。

4. 核对同名文件，按实际范围写入独立目标路径，并比对 SHA-256。确认副本字节一致后，按业务
   Skill 的清理规则处理属于本轮的临时文件。报告绝对路径、日期范围、行数和验证结果。

   对已核对范围的 XLSX，可用以下命令验证容器并无覆盖地落地。先把 `SOURCE` 设为本轮大小已
   稳定的临时文件绝对路径，`DEST` 设为实际范围对应的绝对路径。工作表与范围的核对遵循报表 Skill。

   ```bash
   python3 - "$SOURCE" "$DEST" <<'PY'
   import hashlib
   import shutil
   import sys
   import tempfile
   import zipfile
   from pathlib import Path

   source, dest = (Path(arg) for arg in sys.argv[1:])
   with zipfile.ZipFile(source) as book:
       entries = set(book.namelist())
       if (book.testzip() is not None
               or not {"[Content_Types].xml", "xl/workbook.xml"} <= entries
               or not any(name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
                          for name in entries)):
           raise SystemExit("XLSX structure or integrity check failed")

   with tempfile.TemporaryDirectory(dir=dest.parent) as folder:
       staged = Path(folder) / dest.name
       shutil.copyfile(source, staged)
       with source.open("rb") as original, staged.open("rb") as copy:
           def digest(stream):
               sha = hashlib.sha256()
               for block in iter(lambda: stream.read(1024 * 1024), b""):
                   sha.update(block)
               return sha.hexdigest()

           if digest(original) != digest(copy):
               raise SystemExit("Copied bytes differ")
       dest.hardlink_to(staged)
   print(dest.resolve())
   PY
   ```

## 7. 操作边界

浏览器只访问官方后台和已确认的报表控件。凭据、Cookie、签名下载地址和私有配对链接留在
浏览器或本机组件。来源受阻时保留任务、日期范围、页面状态及已校验的原件，方便精确续跑。
