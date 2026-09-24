# Kimi Codex Memory

让 Kimi Code 在新对话中延续过去的项目背景、用户偏好与已确认的决策。

安装后默认使用 **Kimi 当前选中的默认模型与登录方式**：既支持 Kimi 订阅，
也支持你在 Kimi 中配置的第三方模型。通常不需要填写任何 Memory 配置，
也不需要另装 Python、Node.js、uv 或另一份 Kimi。

支持 Windows、macOS、Linux 的 x64 / ARM64。使用 OpenAI Chat Completions、
OpenAI Responses 或 Anthropic Messages 接口；暂不支持 Gemini API。

这是独立开源项目，不是 Moonshot 或 OpenAI 官方产品。后台整理会读取符合
条件的历史会话，并消耗你所选模型的额度。原始会话不会被插件删除。

## 安装

先确认你已经能在 Kimi Code 中正常对话。然后在 Kimi 里输入：

```text
/plugins marketplace https://raw.githubusercontent.com/WAcry/kimi-codex-memory/main/marketplace.json
```

选择 **Kimi Codex Memory**，按 Enter 安装，再运行 `/new` 开始新会话。
也可以直接安装最新的完整插件包：

```text
/plugins install https://github.com/WAcry/kimi-codex-memory/releases/latest/download/kimi-codex-memory.zip
```

请使用完整插件包，不要使用 GitHub 的 **Download ZIP** 或直接安装源码仓库
URL；源码包不包含各平台的运行程序。

Kimi 必须在 PATH 上，Git 必须可用。Windows 按 Kimi 官方要求安装 Git for
Windows 即可；不要求管理员权限、创建符号链接权限或开启开发者模式。

首次安装时还没有记忆，属于正常状态。默认整理最近十天内更新、已闲置至少
六小时的历史会话，每批最多两个；不会马上总结你正在进行的会话。

## 日常使用

正常使用 Kimi 即可。新会话会自动收到一份简短记忆摘要，需要细节时，Kimi
自行查阅相关记录。摘要不会在每轮对话或每次后台更新后重复注入。
首次检查时还没有摘要，就不会在工作进行到一半时因为首份记忆生成而自动
补入；新会话会自然使用它。普通恢复沿用已有上下文，不重复添加摘要。
压缩会开始新的上下文阶段，因此保留压缩后下一次用户输入时的记忆恢复。

记忆来自过去，不是当前事实的保证。代码、配置或项目状态可能已经改变，
Kimi 仍应在重要的地方进行现场验证。

**额度用完、登录过期、网络失败或 Kimi 接口变化，只会暂停相关后台生成。
已经发布的记忆仍可照常注入、检索与读取。** 普通对话不会被这些错误阻断，
也不会反复弹出要求你处理后台问题的提示。

想显式修改记忆，直接告诉 Kimi：

```text
请记住：这个项目的发布分支是 release。
请纠正之前关于这个项目的记忆：现在改用 pnpm，不再使用 npm。
请忘记之前记录的那条临时偏好。
```

请求先被记录，后台下次成功整理时再应用；排队成功不代表已经完成遗忘。

## 更新

Kimi 的插件管理器负责安装和更新。重新打开本项目的 Marketplace，看到新
版本后按 Enter 更新，再运行 `/new` 或 `/reload`。不需要重新配置模型。

```text
/plugins marketplace https://raw.githubusercontent.com/WAcry/kimi-codex-memory/main/marketplace.json
```

插件**不会自动升级、降级或重装 Kimi Code**。Kimi 从 2.1.0 升到 2.1.3、
2.1.7 等版本时，不会仅因版本号变化而停工；仍会尝试当前接口。只有实际读取
失败或结构不兼容时才暂停相关生成，升级插件后可继续处理。

目前使用原生的用户可控更新，不在会话 hook 中偷偷下载和替换代码。
更新插件保留本地记忆与个人配置。

你升级 Kimi 时，能正常工作的后台连接会完成当前读取，不强制热重启；
辅助进程结束后，下次自然使用当前安装。升级期间短暂的启动或读取失败会
静默重试，不影响已有记忆。插件只限制自己后台调用触发自动更新，不改变
你正常使用 Kimi 时的更新设置。

## 可选配置

**没有配置文件也可以工作。** 默认数据目录是 `~/.kimi-codex-memory/`，
Windows 对应你的用户目录。通过 `KIMI_MEMORY_HOME` 可以显式更改位置。

两份可选文件分别控制自动注入和后台生成，只填写需要覆盖的值，不必复制
全部默认值。修改后在下次相应操作时生效。

### 使用另一款已在 Kimi 配置好的模型

在数据目录新建或编辑 `worker.toml`：

```toml
[extraction]
model = "your-kimi-model-alias"
```

默认两个阶段使用同一模型。需要为合并单独指定时：

```toml
[consolidation]
model = "your-other-kimi-model-alias"
```

这里填写 Kimi 中已有的**模型别名**，无需再填写对应的地址或密钥。
合并模型需要支持工具调用。用户在 Kimi 中配置的上下文上限优先；没有可用
的窗口信息时，按 256,000 tokens 回退，并以有效窗口的 70% 规划提取预算。

### 暂停生成，但保留已有记忆

`worker.toml`：

```toml
[generation]
enabled = false
```

### 关闭自动注入

`reader.toml`：

```toml
enabled = false
```

这不删除记忆，也不自动暂停生成。需要停用整个插件时，在 Kimi 中执行：

```text
/plugins disable kimi-codex-memory
```

### 排除某些项目

`worker.toml`：

```toml
[generation]
exclude_cwds = ["/home/example/private-*", "C:/Users/example/private-*"]
```

使用完整目录与通配符。Windows 路径也可以写成正斜杠形式。排除项优先；
已有的范围外记忆会在下一次成功整理时退出，而不是保存配置的瞬间删除。

## 排查问题

`/plugins info kimi-codex-memory` 可以查看安装状态。模型或额度问题先在
Kimi 中确认：默认模型是否能完成普通对话。修复登录或配置后，后续会话会
再次唤醒后台，失败任务不会被当成已经成功处理。

数据目录中的 `worker-status.json` 记录最近的后台状态；不包含聊天正文或
密钥。`paused` 不等于记忆读取被关闭。

若目录中已有旧版开发项目的数据 `~/.kimi-code-memory/`，且没有新数据目录，
插件会继续使用旧目录，不会默默丢掉已有记忆。旧开发插件仍在启用时，请先
`/plugins disable kimi-code-memory`，避免同时启用两套注入。

## 卸载

```text
/plugins remove kimi-codex-memory
```

插件移除不会自动清空你的记忆目录。需要彻底删除时，在停止插件后自行删除
数据目录。已经进入旧会话的上下文也不会因此被自动撤回。

## 开发与贡献

开发规则见 [AGENTS.md](AGENTS.md)，产品决策见 [ADR](docs/adr/)，
架构与验证见 [DESIGN](docs/design/)，上游来源见 [upstream](docs/upstream.md)。
