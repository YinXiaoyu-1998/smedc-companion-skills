# WorkBuddy 上的企业智脑（SMEDC）配套 Skills

WorkBuddy 使用 BrowserSkill 的 `bsk` CLI 和本机 Chrome 扩展，在独立的 Agent Window 采集美团来源。
配套 Skills 从同一份 `skills/` 源码生成，安装到 WorkBuddy 的发现目录。

- [上手指南](GETTING_STARTED.md)涵盖核心 Skill、SMEDC launcher、BrowserSkill 和首次下载。
- [安装与验证](INSTALL.md)涵盖配套 Skills 的安装、升级和文件校验。
- [网页操作手册](references/browser-skill.md)给出命令与美团 iframe 的下载路径。
- [能力映射](HOST_MAP.md)与[工作流手册](WORKFLOWS.md)说明中央动作、续轮和阶段阻塞。

真实验收覆盖了「自助营业取数」的一次原件下载。定时触发、其他报表和中央上传各有自己的验收条件。
邮件阶段使用本地交付，中央与本地状态分别记录。
