# ADR 0008：单一完整 Prompt 与发布前 1.0.0 替换

状态：接受。来源：用户要求重新核实 Plugin System Prompt 的自动加载，
最小调整 Codex v2 提示词，移除重复与宿主适配附录；明确授权在没有
真实用户的前提下删除旧 Release，重新发布 1.0.0。

## 实际宿主机制

启用且正常的 Kimi 插件可以自动贡献 systemPrompt/systemPromptPath，
默认 agent 模板包含它，不需要 Composer 点名。自定义 SYSTEM.md/agent
模板可以不包含 plugin_sections/base_prompt，此时不会贡献静态指令。
这与按需 Skill、sessionStart.skill 及外部 SessionStart hook 是四个
不同机制。SessionStart 的 stdout 不进入模型；UserPromptSubmit 会。

不能把规则只放静态层、hook 只传摘要，否则自定义模板会缺规则；也不
应为判断静态层是否加载而在离线 reader 引入宿主 API/配置推断。

## 决策

移除 Memory 的 systemPromptPath、plugin/system.md 和重复的 reader
system 模板。保留唯一完整的 v2 阅读 prompt，在原定上下文边界通过
UserPromptSubmit 注入规则、绝对目录和摘要，不依赖用户是否调用插件。

延续 ADR 0006：无已发布摘要时不提供完整记忆块、不等首份生成后补入；
普通 resume 不重复；compact 后下一用户输入恢复。去掉静态副本后不
声称同一 turn 的 compact 后步骤必然还有完整规则，也不新增热注入接口。
无摘要时的入口由 ADR 0009 后续收窄修正：只提供显式 notes 写入指引，
不提供历史、检索或引用规则；既有单一 hook 和不晚注入的决策不变。

Kimi 会把没有 message 的 stdout 当成文本，因此 {} 不是无操作，而
是每轮一个空对象消息。成功无输出/失败放行必须真正留空 stdout，包括
缺失运行程序时的 launcher，不改变内部 handle 的结构化结果。

## Prompt 和来源规范

Codex 原文归档在 vendor/codex/memories，继续记录 commit/hash。实际
运行模板在 prompts 中直接做最小修改，Python 只填数据占位符，不再
替换自然语言段落、不在摘要后添加 Kimi host adaptation。

来源摘要和合并索引统一 session_id；它是过去来源会话的完整标识。
阅读 prompt 明确要求复制这个头部值到既有 rollout_ids 引用字段，
不要求理解 Codex thread/UUID，不从当前会话 ID 或文件名推导。保留
原版 XML 标签、rollout_summaries 目录和 JSON 输出字段，不增加兼容
分支。notes 使用稳定写入目录，不能写入不可变 generation 的快照。

## 本次发布例外

用户确认仍无真实使用者，因此保留版本号 1.0.0。完成测试和各平台构建
后删除明确列出的旧 Release/tag（v0.2.0、v0.2.1、旧 v1.0.0），以新
提交重新创建 v1.0.0，发布经过验证的包。保留 main 的开发历史，不
force-push 主分支，不删除用户数据，不把替换已发布版本变成常规流程。

release-v1 fixture 的来源头部/索引在本次重发前统一 session_id，重算
相应文件 hash，不添加旧 header 的兼容解析。重新发布后的 1.0.0 才
是冻结基线；后续有真实用户时恢复 ADR 0007 的兼容和不可覆盖发布规则。
