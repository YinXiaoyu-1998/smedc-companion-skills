# 安装与验证 WorkBuddy 配套 Skills

从同一份配套 Skills 源码仓库运行以下命令。员工上手顺序见[上手指南](GETTING_STARTED.md)。

```bash
python3 workbuddy/bsk/build.py check
python3 workbuddy/bsk/build.py install --root ~/.workbuddy/skills
python3 workbuddy/bsk/build.py verify --root ~/.workbuddy/skills
```

`check` 核对仓库中的生成文件。修改上游 Skill 或适配规则后，运行
`python3 workbuddy/bsk/build.py build` 更新生成文件，再审阅变更。

`install` 会预先检查整批写入路径，要求安装目标位于 WorkBuddy 发现根，拒绝 Codex 发现目录、
源码仓库、Home 目录及写入目标上的符号链接。它逐个替换发行包内的文件，最后更新各 Skill 的入口，
保留额外的本地文件。已有同名 Skill 会升级到本次发行内容。
`verify` 通过与安装共用的清单核对每个发行文件与当前源码的内容。失败时修复显示的路径并重跑安装。

每个安装副本自带说明、运行脚本、iframe 导出脚本和文件清单。可直接从任一已安装的 Skill
目录运行 `python3 workbuddy/scripts/preflight.py`，检查可用文件、CLI、daemon、扩展连接等本机依赖。
源码仓库中的同一命令会额外验证生成文件。SMEDC 身份和实际浏览器会话按上手指南验证。

升级后，开一个新 WorkBuddy 会话重新加载 Skills。在 Windows PowerShell 中使用本机的
`python` 命令和 WorkBuddy 发现目录绝对路径。
