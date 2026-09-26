# Kimi Codex Memory

让 Kimi Code 在新对话中延续过去的项目背景、用户偏好与已确认的决策。

采用和 Codex 的 Memory V2 几乎完全相同的实现。

安装后默认使用 **Kimi 当前选中的默认模型与登录方式**：支持 Kimi 订阅，
也支持你在 Kimi 中配置的第三方模型。可以修改配置文件来选择其他（更便宜的）模型。

后台 Dreaming 整理会读取符合条件的历史会话，并消耗你所选模型的额度。原始会话不会被插件删除。

这是独立开源项目，非 Moonshot / OpenAI 官方产品。

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

Kimi 必须在 PATH 上，Git 必须可用。Windows 按 Kimi 官方要求安装 Git for Windows 即可。

首次安装时还没有记忆，属于正常状态。默认整理最近十天内更新、已闲置至少六小时的历史会话，每批最多两个。

## 日常使用

正常使用 Kimi 即可，无需在输入框点名或调用本插件。
新会话/压缩后会自动收到一份简短记忆摘要，需要细节时，Kimi 自行查阅相关记录。
压缩会开始新的上下文阶段，因此保留压缩后下一次用户输入时的记忆恢复。
其他 hook 拦截了首条输入时，下一次输入仍会尝试提供记忆，不会因为文本
已经准备好就认定投递完成。正常会话继续使用原快照；长时间休眠后原快照
已被清理时，会受控地提供当前可用快照，避免一直引用不存在的路径。

记忆来自过去，不是当前事实的保证。代码、配置或项目状态可能已经改变，Kimi 仍会在重要的地方进行现场验证。

一般来说，记忆由后台 Dreaming Agent 生成。但是如果想显式修改记忆，直接告诉 Kimi：

```text
请记住：这个项目的发布分支是 release。
请纠正之前关于这个项目的记忆：现在改用 pnpm，不再使用 npm。
请忘记之前记录的那条临时偏好。
```

请求先被记录，后台下次成功整理时应用；排队成功不代表已经完成记忆/遗忘。
正式发布中不保留处理用的 diff 或 Git 历史。但从当前记忆移除不等于
彻底擦除所有本地副本：旧快照、notes、数据库和原聊天有不同生命周期。

删除、归档或关闭一个历史会话不会让其他会话的记忆生成一起停住。个别
历史/模型输出有问题时，跳过该项并保留正常工作；扫描不完整时暂缓过期
淘汰，避免把“读不到”误当成“可以遗忘”。如果已读完一份历史快照，
随后删除原会话不会取消正在进行的总结；删除聊天也不等于删除已有记忆。

后台模型调用使用 Kimi 原生的底层流式请求与思考/工具消息处理，仍沿用
你在 Kimi 中配置的模型和认证。不需要再设置一套 provider，也不会
启动另一个会操作项目文件的 coding agent。
提取优先采用最后一个合法的结果工具提交。没有合法调用时，才从最终
正文选择最大的、符合记忆结果结构的完整 JSON；不会使用思考内容或
修补损坏 JSON。无需修改模型配置；无效或未完成的结果只让该来源
重试，不覆盖旧记忆。

## 更新

从 **1.2.0** 起，插件默认在使用期间后台检查新版本，每 24 小时最多尝试
一次。发现正式新版后，会在下一次正常输入时显示 Kimi 原生 hook 提醒
卡片，包含当前版本、新版本和安装命令。正常情况下，同一新版在同一
数据目录只提醒一次，不会每轮刷屏；拦截或确认丢失时可能稍后再提醒。

提醒不需要模型转述，但卡片内容也会进入当前对话上下文，这是 Kimi
hook 的原生行为。不会自动下载或安装更新，也不会自动升级 Kimi。
只检查本项目的公开 GitHub Release 元数据，不发送聊天、项目路径或
模型凭据；网络失败、限流或离线都静默跳过，不影响现有记忆。

需要先安装一次含此功能的版本，才能收到以后版本的提醒。已有提醒不
会从聊天历史撤回；新版本必须仍有可用的完整安装包才会被推荐。

Kimi 的插件管理器负责安装和更新。重新打开本项目的 Marketplace，看到新
版本后按 Enter 更新，再运行 `/new` 或 `/reload`。不需要重新配置模型。

```text
/plugins marketplace https://raw.githubusercontent.com/WAcry/kimi-codex-memory/main/marketplace.json
```

插件版本独立于 Kimi 版本。当前最低支持 **Kimi 2.1.0**，固定实现及当前
完整平台测试基线为 **2.1.1**；新版本继续尝试实际接口，不要求数字相等。
插件**不会自动升级、降级或重装 Kimi Code**。Kimi 从 2.1.0 升到 2.1.3、
2.1.7 等版本时，不会仅因版本号变化而停工；仍会尝试当前接口。只有实际读取
失败或结构不兼容时才暂停相关生成，升级插件后可继续处理。
升级修复的 requester 会为旧失败任务重新提供一次重试预算，不重做
已经成功的摘要。状态里的 degraded 表示局部跳过、其他处理仍可继续；
paused 才表示该批整体无法继续。两者都不关闭已有记忆的读取与注入。
当前更新由你在 Kimi 原生插件管理器中确认，不静默替换安装。将来需要
提高最低 Kimi 版本的破坏性变更，会通过插件大版本及升级说明告知。

## 可选配置

**没有配置文件也可以工作。** 默认数据目录是 `~/.kimi-codex-memory/`。
通过 `KIMI_MEMORY_HOME` 可以显式更改位置。
`reader.toml` 和 `worker.toml` 分别控制自动注入和后台生成，另有可选
`updates.toml` 控制更新提醒。只填写需要覆盖的值，不必复制全部默认值。
修改后在下次相应操作时生效。

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

这里填写 Kimi 中已有的**模型别名**，无需再填写对应的地址或密钥。合并模型需要支持工具调用。

### 暂停生成，但保留已有记忆

`worker.toml`：

```toml
[generation]
enabled = false
```

### 关闭指令自动注入

`reader.toml`：

```toml
enabled = false
```

这不删除记忆，也不自动暂停生成或关闭更新提醒。需要停用整个插件时，在 Kimi 中执行：

```text
/plugins disable kimi-codex-memory
```

### 关闭更新检查和提醒

在数据目录创建或编辑 `updates.toml`：

```toml
enabled = false
```

这会关闭新的检查和提醒，不影响记忆读取或生成，也不修改 Kimi 自己的
自动更新设置。修改文件即可生效，不需要重新安装插件。

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
额度、认证和暂时网络问题会延后重试，不消耗来源的永久失败次数。反复
不符合输出契约的来源仍有次数上限；修复默认模型或相关配置后会重新
获得机会，而不需要靠升级插件解锁。已成功且没有变化的会话不会重做。

高级排查时，先用 `/plugins info kimi-codex-memory` 确定插件安装目录。
在该目录下可以执行：

```bash
plugin/run-hook retry --list
plugin/run-hook retry --source session_...
plugin/run-hook retry
```

Windows 使用 `plugin\run-hook.cmd`。这些命令只列出或重置失败任务，
不立即调用模型、不改写成功记忆；下次后台运行仍遵守闲置门槛和预算。
`plugin/run-hook doctor --probe` 可检查宿主契约及兼容提示，不自动更新 Kimi。

## 卸载

```text
/plugins remove kimi-codex-memory
```

插件移除不会自动清空你的记忆目录。需要彻底删除时，在停止插件后自行删除
数据目录。已经进入旧会话的上下文也不会因此被自动撤回。

## 开发与贡献

开发规则见 [AGENTS.md](AGENTS.md)，产品决策见 [ADR](docs/adr/)，
架构与验证见 [DESIGN](docs/design/)，上游来源见 [upstream](docs/upstream.md)。
