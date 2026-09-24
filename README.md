# Kimi Code Memory

让 Kimi Code 在新对话中延续过去的项目背景、用户偏好和已经确认的决策。

它会从合适的历史会话生成记忆，在后续对话中提供一份简短摘要，并让 Kimi
在需要时查阅更具体的记录。记忆来自过去，不替代对当前代码和事实的验证。

**后台生成暂时不可用时，已经生成的记忆仍可照常注入和查阅。**
Kimi 升级、模型请求失败、凭据过期或生成配置写错，都不应让已有记忆一起失效。

这是独立项目，不是 Moonshot 或 OpenAI 官方产品。当前面向 Linux/macOS，
需要 Python 3.11+、Git，以及 Kimi Code 2.1.0。其他 Kimi 版本默认暂停自动生成，
但不关闭已有记忆的读取。

## 从这里开始

### 1. 准备配置

在这个仓库目录中执行：

```bash
./bin/kimi-memory init
```

默认使用 `~/.kimi-code-memory/`。该命令不会安装 Kimi 插件、读取你的对话，
也不会调用模型。它会创建两份配置：

| 文件 | 控制什么 |
| --- | --- |
| `reader.toml` | 已有记忆的注入和读取 |
| `worker.toml` | 历史读取、后台生成、模型与用量限制 |

再次运行 `init` 不会覆盖已有配置。

### 2. 配置生成使用的模型

编辑 `~/.kimi-code-memory/worker.toml` 中已经存在的 `[extraction]`，
不要重复添加同名配置段。使用提供 Chat Completions 接口的服务时：

```toml
[extraction]
protocol = "openai"
base_url = "https://YOUR_PROVIDER/v1"
model = "YOUR_MODEL_ID"
api_key_env = "KIMI_MEMORY_API_KEY"
```

这里的 `openai` 表示接口格式，不要求使用 OpenAI 的模型。
`base_url` 填接口根路径，不要填到 `/chat/completions`。

在**启动 Kimi 的同一个终端环境**中设置凭据：

```bash
export KIMI_MEMORY_API_KEY='YOUR_API_KEY'
```

默认用这个模型同时生成会话摘要和整理总摘要；整理所用模型必须支持工具调用。
生成会消耗你所选服务的额度。不要把真实密钥提交进仓库。

已有合适的 Kimi provider 配置时，也可以复用它：

```toml
[extraction]
kimi_provider = "YOUR_PROVIDER_NAME"
api_key_env = ""
protocol = "openai"
base_url = "https://YOUR_PROVIDER/v1"
model = "YOUR_MODEL_ID"
```

`YOUR_PROVIDER_NAME` 是 Kimi 配置中的 provider 名称，不是模型别名。支持该 provider
配置的 API key、环境变量凭据，以及尚未过期的文件型 OAuth 凭据。当前不支持 keyring
或自行刷新 OAuth；凭据过期后，通过 Kimi 刷新，再重试生成。

使用 Anthropic Messages 接口时，将 `protocol` 改为 `anthropic`，并填对应服务的
`base_url` 与模型标识。

### 3. 检查配置

```bash
./bin/kimi-memory doctor
```

默认只做本地检查，不调用模型。检查与 Kimi 的连接时：

```bash
./bin/kimi-memory doctor --probe
```

这可能短暂启动一个仅本机可访问的 Kimi 辅助服务，但仍不会调用生成模型。
如果提示找不到 Kimi，编辑 `worker.toml` 中的 `api.kimi_command`，填入正确的绝对路径：

```toml
[api]
kimi_command = ["/absolute/path/to/kimi"]
```

### 4. 安装到 Kimi

```bash
./bin/kimi-memory plugin
```

将输出里的 `install_command` 粘贴到 Kimi 中执行，然后开启一个新会话。
生成的插件会固定使用本次命令的 Python 环境；之后不要删除或移动这份仓库／Python 环境。

也支持标准 Python 包安装：`python3 -m pip install .`。安装后可直接使用
`kimi-memory`，而不必输入 `./bin/kimi-memory`。

### 5. 查看是否开始工作

```bash
./bin/kimi-memory status
```

首次安装时还没有记忆，这是正常的。默认只处理最近十天内更新、已经闲置至少六小时
的历史会话，每次最多处理两个，不总结当前正在使用的会话。新会话活动会唤醒后台处理。

需要主动检查一次时：

```bash
./bin/kimi-memory worker --once
```

这个命令会按配置使用模型，仍遵守闲置门槛、冷却时间和额度限制。

## 常用配方

### 只暂停生成，不停用已有记忆

在 `worker.toml` 中设置：

```toml
[generation]
enabled = false
```

已有记忆仍会注入，Kimi 仍能按需查阅。恢复为 `true` 后，在新会话中继续使用，
或手动运行 `worker --once`。

### 关闭自动记忆注入

在独立的 `reader.toml` 中设置：

```toml
enabled = false
```

这不会删除或隐藏记忆文件，也不会自动暂停生成；需要暂停两项自动行为时，
同时修改两份配置。手动读取文件仍然可用。要同时移除 Kimi 的按需查阅指引，
在 Kimi 中移除本插件；已经进入旧会话的上下文不会因此被自动撤回。

### 控制成本与处理速度

下面的值是示例；直接修改已有字段：

```toml
[generation]
max_extractions = 1
extraction_concurrency = 1
max_daily_model_calls = 20
max_run_model_calls = 10
min_idle_hours = 6.0
consolidation_cooldown_seconds = 21600
```

一次整理可能使用多次模型请求，所以“每天二十次请求”不等于“每天二十个会话”。
每天额度按 UTC 日期重置；这些限制控制请求数量，不是账单金额保证。

### 为整理使用另一个模型

```toml
[consolidation]
model = "YOUR_CONSOLIDATION_MODEL_ID"
```

未填写的字段继承 `[extraction]`。也可以分别覆盖 `protocol`、`base_url`、
`api_key_env` 等设置。

### 只处理指定项目

```toml
[generation]
include_cwds = ["/home/example/git/*"]
exclude_cwds = ["/home/example/git/private-*"]
exclude_session_ids = []
```

使用完整路径和通配符。排除项优先。收紧范围后，之前范围外的记忆会在下一次
成功整理时退出，不会在编辑配置的瞬间被删除。

### 调整记忆规模

```toml
[generation]
retention_days = 30.0
max_consolidation_sources = 256
max_memory_summary_bytes = 10000
max_rollout_summary_bytes = 9000
```

如增大总摘要，也相应调整 `reader.toml` 的 `max_summary_bytes`，避免注入时被截短。
记忆保留会考虑实际引用；不是到期立即删除，也不会替你删除原始聊天记录。

### 显式记住、纠正或忘记

可以直接在 Kimi 对话里提出要求，也可以使用命令：

```bash
./bin/kimi-memory note remember '默认先给结论，再给验证步骤。'
./bin/kimi-memory note correct '项目现在使用新的测试命令，旧命令不再适用。'
./bin/kimi-memory note forget '不要继续保留那条已经废弃的偏好。'
```

这些请求会排队等待后台整理，不代表已即时修改所有记忆。生成暂停时，请求仍会保留。

### 只在本地查看注入内容

```bash
./bin/kimi-memory render
rg -n -i '关键词' ~/.kimi-code-memory/memories_v2/rollout_summaries
```

即使 Kimi 的 Web 服务或生成模型离线，这些操作仍然可用。

### 已经在运行 Kimi Web

默认会优先复用同一数据目录下的合适服务；也可以指定：

```toml
[api]
server_url = "http://127.0.0.1:58627"
auto_start = false
```

只使用 CLI 时，不需要手动打开浏览器。后台可按需启动本机辅助服务，
默认从 `59627` 开始寻找可用端口，读取完成后关闭自己启动的实例。
它不会替你停止已有 Web 服务、轮换 token 或打开远程访问。

### 放到其他目录

```bash
export KIMI_MEMORY_HOME="$HOME/my-kimi-memory"
./bin/kimi-memory init
./bin/kimi-memory plugin
```

Kimi 本身的数据目录由 `KIMI_CODE_HOME` 决定；不要将两者混淆。不同 Kimi home
需要分别生成对应安装环境的插件，并使用不同 memory home，避免混合用户或配置。

## 遇到问题时

| 现象 | 处理方式 |
| --- | --- |
| Kimi 升级后生成暂停 | 运行 `doctor --probe` 查看版本信息；更新本项目后再恢复。已有记忆仍可使用。 |
| `incompatible_kimi` | 当前接口或版本尚未验证。不要仅为消除提示就随意放行。 |
| `configuration_error` | 检查 `worker.toml` 的字段名、类型、模型和凭据来源。读取配置独立，不必删除记忆。 |
| `incomplete_history` | 历史正在变化，或达到读取上限。结束当前活动后重试；很长的历史可调整读取上限。 |
| 模型额度不足／请求失败 | 降低批量和额度，或修复模型配置。请求失败不会覆盖上次发布的记忆。 |
| `pending_citations` | 有新的对话活动，后台先等引用记录同步，再继续整理。 |
| 初次安装没有摘要 | 确认已有符合闲置条件的历史，且模型配置可用。 |
| 调整配置却没有立刻整理 | 仍可能处于成功冷却期或失败重试等待期；`status` 查看最近结果。 |

`worker.toml` 提供 `allow_unverified_version` 作为明确接受风险的选项。默认不要开启；
它不会跳过实际返回内容的检查，也不能让不兼容的接口自动变得兼容。

当前不会复制完整聊天历史或所有图片附件。生成前会做尽力脱敏，但这不能保证清除
所有秘密；模型会收到所选会话的必要文本。请只配置你信任的模型服务，并排除不应处理的项目。

## 升级与卸载

更新仓库或重新安装 Python 包后，重新执行 `plugin` 并在 Kimi 中重新安装／加载插件。
已有记忆无需删除。若只是移动仓库，也要重新生成插件，更新它记录的执行路径。

在 Kimi 中执行 `/plugins remove kimi-code-memory` 可停止自动接入。已保存的记忆仍保留
在本地；确认不再需要后，由你自行备份或删除数据目录。
