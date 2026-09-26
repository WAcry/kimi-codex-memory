# 上游基线与原版模板

精确 commit、源文件路径及 SHA-256 在仓库根目录 `upstream.toml` 中。
原始五份模板归档在 vendor/codex/memories，测试逐个核对原文字节 hash。
`runtime_path` 指向基于该原文作最小修改的执行模板；两者不能混称为原版。

Codex 源码基线：`5c5308fc9a9ee789049d646ef11e5400384b9c6f`。
Kimi 源码基线：`a1e4c13d411f75bd327e2c33077daff42ee63582`，产品版本 `2.1.0`。

归档原样保存：stage-one system/input v2、consolidation v2、read-path v2、
ad-hoc instructions，以及上游 LICENSE/NOTICE。执行模板可以直接比较：

```bash
git diff --no-index vendor/codex/memories/read_path_v2.md src/kimi_memory/prompts/read_path_v2.md
```

ad-hoc instructions 的执行版仍然逐字相同。未向模型提供第二套静态规则
或宿主适配附录；具体原因和原生请求验证见 DESIGN 07、ADR 0008。

## 显式适配

来源文件与合并索引统一用 session_id；阅读 prompt 直接要求复制这个值
到保留的 rollout_ids 引用字段。提取前由原生 API 返回当前有效历史，
输入包含真实 session_id，不伪造文件路径或 URI。

预算可配置，使用 Kimi 同类的 ASCII/非 ASCII token 估算，不要求字节数或
比例逐个相同。合并只提供 list/read/write-summary，不暴露 shell 和用户文件。

发布采用独立 generation 与原子指针，替代原地多文件覆盖。引用收据基于原生
transcript 暴露的完成信息，而不是不存在于该接口里的 raw step UUID。

注入只采用当前 Kimi 实际可用的 UserPromptSubmit，提供一份自包含的
规则与摘要；SessionStart 只唤醒，PostCompact 才重置检查状态。reader
仍与生成独立。无摘要时不提供完整阅读片段，只提供 ADR 0009 中的简短
notes 写入指引；这是明确的小型体验调整，不伪称上游默认也注入这段。
Codex 的专用 add_ad_hoc_note 工具可以独立于摘要暴露（需要启用专用
工具），其描述的显式请求门槛与只新增 note 语义是短指引的参照。

| 执行模板 | 相对原文的必要修改 |
| --- | --- |
| read_path_v2 | session summary 术语、Grep/rg、独立 notes 路径、异步 notes 语义、session_id 到引用字段的直接映射 |
| stage_one_input_v2 | session 上下文与真实 ID；过滤后的 Kimi transcript；最终交付使用结果 Tool |
| stage_one_system_v2 | rollout 文本称谓改为 session，结果通过 submit_memory_extraction；双字符串字段和内容规则不变 |
| consolidation_v2 | session_id 索引、预算占位符和实际可用的 write_summary 工具；其余格式/筛选要求保留 |
| ad_hoc_instructions | 无修改 |
| notes_only | 无完整摘要时使用的自有短模板，沿用明确请求写 note 与后续合并语义，不增加检索/引用规则 |

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
可以任意执行 shell 的工具描述，却提供完全不同的实现。原文归档与最小
修改后的执行模板、宿主工具声明可以独立审计。

## 预算

默认闲置 6 小时、来源 10 天、保留 30 天、每批 2 个提取、最多 256 个合并
来源等沿用上游。有效窗口从 Kimi 配置获得后按 70% 规划提取，并为输出及
请求开销留空间；未知窗口回退到用户指定的 256,000，而不是 Codex 的未知
窗口固定输入回退。不会递归追索日志里的 spill 文件。
超长提取结果采用 `utils/string/src/truncate.rs` 的首尾保留与省略字符标记
语义，避免仅保留开头导致最后的纠正消失；标记和上游一样在保留字节预算之外。

## Kimi OAuth 源码复用

`upstream.toml` 的 `kimi_files` 逐个记录原样复制的 OAuth 生命周期、文件
存储、请求头及许可证。不是从用户机器任意加载一份未确定版本的私有模块。
`bridge/auth.ts` 是薄适配，`native/auth.mjs` 是固定依赖构建出的运行文件。
Windows 的原生刷新协调维持上游 best-effort 语义；没有另行承诺严格锁。

## 注入时机追踪

模型请求层另以 [kimi_requester] 指定的 Kimi commit 和
vendor/kimi-requester/files.json 记录 35 个原样源码文件，包含三种
底层 requester、消息解析、thinking 和 Kimi traits。没有 vendoring
整个 engine、配置服务或工具 runner；协议以原生代码为准，记忆输出
验证与调度仍在本项目。SDK/代理依赖锁定并附带实际 bundle 的许可证。
详情与明确边界见 DESIGN 08。

v2 的 ContextContributor 是 thread-context contributor，不是每 turn
的动态记忆刷新。完整上下文构建才读取摘要；缺失文件不贡献 memory prompt。
正常 resume 复用历史 baseline，compact 会重建它。首次生成不会主动通知
前台注入。具体文件、调用链与宿主适配边界见 DESIGN 06 与 ADR 0006。
