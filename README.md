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

记忆来自过去，不是当前事实的保证。代码、配置或项目状态可能已经改变，Kimi 仍会在重要的地方进行现场验证。

一般来说，记忆由后台 Dreaming Agent 生成。但是如果想显式修改记忆，直接告诉 Kimi：

```text
请记住：这个项目的发布分支是 release。
请纠正之前关于这个项目的记忆：现在改用 pnpm，不再使用 npm。
请忘记之前记录的那条临时偏好。
```

请求先被记录，后台下次成功整理时应用；排队成功不代表已经完成记忆/遗忘。

删除、归档或关闭一个历史会话不会让其他会话的记忆生成一起停住。个别
历史/模型输出有问题时，跳过该项并保留正常工作；扫描不完整时暂缓过期
淘汰，避免把“读不到”误当成“可以遗忘”。如果已读完一份历史快照，
随后删除原会话不会取消正在进行的总结；删除聊天也不等于删除已有记忆。

后台模型调用使用 Kimi 原生的底层流式请求与思考/工具消息处理，仍沿用
你在 Kimi 中配置的模型和认证。不需要再设置一套 provider，也不会
启动另一个会操作项目文件的 coding agent。
提取结果通过单一的结果工具提交，不再从普通回答中猜测 JSON。无需修改
模型配置；服务不支持严格 schema 时仍可使用普通工具调用，本地会验证
参数。无效或未完成的结果只让该来源重试，不覆盖旧记忆。

## 更新

Kimi 的插件管理器负责安装和更新。重新打开本项目的 Marketplace，看到新
版本后按 Enter 更新，再运行 `/new` 或 `/reload`。不需要重新配置模型。

```text
/plugins marketplace https://raw.githubusercontent.com/WAcry/kimi-codex-memory/main/marketplace.json
```

插件**不会自动升级、降级或重装 Kimi Code**。Kimi 从 2.1.0 升到 2.1.3、
2.1.7 等版本时，不会仅因版本号变化而停工；仍会尝试当前接口。只有实际读取
失败或结构不兼容时才暂停相关生成，升级插件后可继续处理。
升级修复的 requester 会为旧失败任务重新提供一次重试预算，不重做
已经成功的摘要。状态里的 degraded 表示局部跳过、其他处理仍可继续；
paused 才表示该批整体无法继续。两者都不关闭已有记忆的读取与注入。

## 可选配置

**没有配置文件也可以工作。** 默认数据目录是 `~/.kimi-codex-memory/`。
通过 `KIMI_MEMORY_HOME` 可以显式更改位置。
两份可选文件分别控制自动注入和后台生成，只填写需要覆盖的值，不必复制全部默认值。
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

## 卸载

```text
/plugins remove kimi-codex-memory
```

插件移除不会自动清空你的记忆目录。需要彻底删除时，在停止插件后自行删除
数据目录。已经进入旧会话的上下文也不会因此被自动撤回。

## 开发与贡献

开发规则见 [AGENTS.md](AGENTS.md)，产品决策见 [ADR](docs/adr/)，
架构与验证见 [DESIGN](docs/design/)，上游来源见 [upstream](docs/upstream.md)。
