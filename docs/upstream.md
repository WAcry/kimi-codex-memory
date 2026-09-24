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
