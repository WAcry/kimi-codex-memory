# DESIGN 07：模型实际收到的 Prompt

## 调查和验证

源码基线 Kimi be7d5f5fea7800778e4660cd5f36780ba783bddd（2.1.1），
Codex 5c5308fc9a9ee789049d646ef11e5400384b9c6f。Kimi 原生 2.1.0
命令的真实 HTTP 请求由本地脚本模型截获验证，不调用订阅/付费模型。

Kimi 的四条独立链路（下面路径相对 packages/agent-core-v2/src）：

| 入口 | 实际行为 |
| --- | --- |
| systemPrompt / systemPromptPath | manifest.ts:265–331 在安装/reload 时读取；manager.ts:345–353 返回所有启用且正常的插件指令；profileService.ts:835–843,891–924 汇入 profile，上限 64 KiB 并缓存 |
| 默认 vs 自定义 SYSTEM.md | app/agentProfileCatalog/system.md:82 含 plugin_sections；profile-shared.ts:165–185 按模板变量渲染，自定义可完全不含该变量 |
| sessionStart.skill / Skill | agent/plugin/agentPluginService.ts:79–125 自动加载指定启动 skill；其他 Skill 是另外的按需加载路径 |
| 外部 hooks | SessionStart 在 sessionExternalHooksService.ts:109–120 执行但不追加结果；UserPromptSubmit 在 agentExternalHooksService.ts:335–386 写入 role=user、origin=hook_result 的消息 |

因此 systemPromptPath 不是需要在 Composer 调用才加载的 Skill，但也不能
保证所有自定义 agent 模板都会包含它。默认 profile 会收到旧的静态规则
加动态规则两套重复指导；自定义 profile 可能只收到动态那一套。

## 最终拓扑

```text
启用 Memory 插件（无静态 systemPrompt，也没有 Skill 内容注入）
  SessionStart ───→ 后台通知，不输出 prompt
  UserPromptSubmit ───→ 离线检查本上下文的 receipt
      已检查 / reader 关闭 ───→ stdout 为空
      首次无可用摘要 ───→ 仅显式 notes 写入指引（ADR 0009）
      首次有摘要 ───→ 一份完整 read_path_v2 + 路径 + 摘要
          Kimi 包成 UserPromptSubmit 的 hook_result
          作为用户角色的 hook_result 来源消息加入模型上下文
  PostCompact ───→ 清除 receipt，下一用户输入重建
```

没有去检测或猜测静态系统模板是否被加载，不依赖 API 才能渲染。Kimi
自己的系统规则及其他插件的贡献保持不变。这里不是宣称 Kimi 的 user
hook 与 Codex developer-policy 是相同优先级；后者仍是宿主差异。

## 实际模型角色

插件系统文本会并入 profile.systemPrompt，而 hook 的成功输出经
agentExternalHooksService.ts:370–377 作为 role=user 加入历史。标签
hook_result 是来源/文本包装，不会把消息提升为 system 或变成 tool 结果。

以下路径相对 packages/agent-core-v2/src/human/llm/requester/bases：

| 协议 | 插件 System Prompt 的位置 | hook 的位置 |
| --- | --- | --- |
| Chat Completions | openai/requester.ts:121–129：messages 中的 role=system | messages 中的 role=user |
| OpenAI Responses | openai-responses/format.ts:411–423：顶层 instructions | input 中 role=user 的 message，不是 function_call_output |
| Anthropic Messages | anthropic/format.ts:240–248：顶层 system 文本块 | messages 中的 role=user |

Responses instructions 在 OpenAI 接口中是 system/developer 指令入口，
不是另一个平级 user 文本；不同供应商实际遵循程度不由插件保证。这里
记录 Kimi 的真实编码，并不把三种协议的所有角色抽象成完全相同的层级。
默认静态层较高，也仍可能被自定义模板省略；不为一个 notes 入口再引入
静态/动态双份规则和是否已加载的检测。

## 真正的空操作

原生 internal/userPrompt.ts 中 userPromptHookMessage 先取 message，
没有时取 stdout。返回 {} 会让实际请求多出一个内容为 {} 的 hook_result
消息，即使 memory receipt 已经去重。

现在 hooks.main 只在确有 message 时输出 JSON，否则零字节。JS launcher
失败放行也不输出 {}。原生请求测试对续用前后所有消息计数，而不是仅
测试 Python handle() == {}，避免再次把内部无结果误当成宿主无注入。

## 最小且自包含的文字

read_path_v2 保留原版历史不是当前事实、必要时才下钻、实际使用才引用、
PR 不引用、用户明确要求才改记忆、不得为了引用额外读文件等要求。
增加的只有准确工具/目录信息、note 保存与后续合并区别、session_id 的
直接复制规则；不存在 Kimi/Codex 对比附录或重复兜底说明。

例：来源文件开头 session_id: session_<完整 ID>；最终引用保留
oai-mem-citation/citation_entries/rollout_ids 外壳，把 header 中的值
原样放入 rollout_ids。session_id 指历史来源，不是当前会话或文件 hash。

读取目录 = 发布 generation，notes 目录 = 固定的
memories_v2/extensions/ad_hoc/notes。模板分别使用 base_path/notes_path
占位符。总摘要作为最后一个数据值填入，不再对已填入的历史文本进行
UUID、措辞或路径替换。

Phase 1 使用真实 session_id 和过滤后的会话证据，不构造不可读取的
kimi-session: URI；Phase 2 索引也使用 session_id。两阶段保留原版
输出 schema、记忆结构和核心选择规则；原文与可执行模板的 diff 可直接
审计。write_summary 的说明直接写入模板，不再加结尾的工具适配附录。

## 回归范围

tests/test_native_prompts.py 用另一个探针插件证明静态指令默认自动出现、
自定义 SYSTEM.md 可排除它，但 Memory hook 在两种情况下都完整且只出现
一次；还测继承 base_prompt、普通 resume、首次发布后不补入和禁用插件。
worker 配置和 DB 被故意破坏后，模型收到的记忆仍然完整。

tests/test_prompt_contract.py 检查实际 reader/提取/合并请求、note 路径、
引用示例与来源 ID 一致，以及原始记忆内容不会被模板后处理误改。测试用
脚本模型只证明组合和传输正确，不声称真实模型的理解与引用永远正确。

ADR 0009 增加无摘要时的独立短 notes 模板，不改变完整阅读模板。测试
覆盖三种协议的顶层指令与 user hook 角色、默认和自定义系统模板；已有
摘要时不叠加短模板，无摘要时没有历史/引用内容。另用本地脚本模型调用
真实 Kimi Write，验证首次请求也能把 note 落盘，无需 memory_summary。
