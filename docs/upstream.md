# 上游基线与原版模板

精确 commit、源文件路径及 SHA-256 在仓库根目录 `upstream.toml` 中。测试逐个
核对原版文件的字节 hash。它们不能被 formatter 或适配逻辑改写。

Codex 源码基线：`5c5308fc9a9ee789049d646ef11e5400384b9c6f`。
Kimi 源码基线：`a1e4c13d411f75bd327e2c33077daff42ee63582`，产品版本 `2.1.0`。

原样保存：stage-one system/input v2、consolidation v2、read-path v2、ad-hoc
instructions，以及上游 LICENSE/NOTICE。额外的 `reader_system_kimi.md` 是
本项目的宿主适配提示，不是伪称原版的模板。

## 显式适配

Kimi 原生 session ID 替代裸 UUID 约束；来源路由使用 `kimi-session:` 标识，
不伪造 Codex JSONL 路径。提取前由原生 API 返回当前有效历史。

预算可配置，使用 Kimi 同类的 ASCII/非 ASCII token 估算，不要求字节数或
比例逐个相同。合并只提供 list/read/write-summary，不暴露 shell 和用户文件。

发布采用独立 generation 与原子指针，替代原地多文件覆盖。引用收据基于原生
transcript 暴露的完成信息，而不是不存在于该接口里的 raw step UUID。

注入采用当前 Kimi 实际可用的 UserPromptSubmit 加稳定系统规则。SessionStart
只重置和唤醒。读取失败隔离要求高于对 Codex 内部模块布局的字面镜像。

没有 v1、raw_memories.md、MEMORY.md、自动生成 skills、向量数据库或完整历史
的第二份存储。详细运行边界与验证方式见 `design/`，不可随意改变的决策见 `adr/`。

## Feature flags 与工具表面

此基线 `features.memories` 为 Stable 但默认关闭；`MemoriesConfig.version`
默认 v1。本项目明确只实现用户选定的 v2，不复制 v1 默认选择。
`generate_memories` / `use_memories` 分开，`dedicated_tools` 默认 false。
`MemoriesConfig` 没有 every-prompt / refresh-on-change 开关，因此本项目
不提供这两种行为。来源：`config/src/types.rs`、`features/src/lib.rs`、
`ext/memories/src/extension.rs`（相对于 codex-rs）。

默认前台直接利用文件工具，不需要自建另一套检索 MCP。可选专用工具的描述
位于 `ext/memories/src/tools/{read,search,list,ad_hoc_note}.rs`：read 是
相对路径、行偏移和行数限制；search 是子串匹配与可选分隔符归一化。其读
预算为 20,000 tokens，摘要注入预算为 2,500 tokens；这不同于总摘要文件的
10,000 字节上限。本项目前台使用 Kimi 的原生工具，不伪称其描述与 Codex
通用工具逐字相同。

Codex phase2 会启动隔离的 coding agent；其普通工具来自 core 的工具体系，
并不是 memory-v2 专有 read/write 工具。这里保留受限的三个文件工具，是
外置执行器必要的权限边界：描述必须准确反映实际能力，不能复制一个声称
可以任意执行 shell 的工具描述，却提供完全不同的实现。任务 prompt 原样
保存，与这些宿主工具声明分开审计。

## 预算

默认闲置 6 小时、来源 10 天、保留 30 天、每批 2 个提取、最多 256 个合并
来源等沿用上游。有效窗口从 Kimi 配置获得后按 70% 规划提取，并为输出及
请求开销留空间；未知窗口回退到用户指定的 256,000，而不是 Codex 的未知
窗口固定输入回退。不会递归追索日志里的 spill 文件。

## Kimi OAuth 源码复用

`upstream.toml` 的 `kimi_files` 逐个记录原样复制的 OAuth 生命周期、文件
存储、请求头及许可证。不是从用户机器任意加载一份未确定版本的私有模块。
`bridge/auth.ts` 是薄适配，`native/auth.mjs` 是固定依赖构建出的运行文件。
Windows 的原生刷新协调维持上游 best-effort 语义；没有另行承诺严格锁。
