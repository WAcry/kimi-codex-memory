# DESIGN 06：实际调用链与最小宿主适配

## 调查基线

Codex：`5c5308fc9a9ee789049d646ef11e5400384b9c6f`。
Kimi：`be7d5f5fea7800778e4660cd5f36780ba783bddd`（2.1.1 源码）。
这是代码追踪结论，不是声称运行了整个 Codex Rust 集成测试。

## memory v2 不是每轮动态上下文

`codex-rs/ext/memories/src/extension.rs:56–104`：
MemoriesExtension 实现 `contribute_thread_context`，没有 memory 的
`contribute_turn_context` 回调。v2 在这里按片段输出 developer policy。

`ext/memories/src/prompts.rs:35–64`：每次完整上下文贡献时读取
memory_summary.md；文件缺失或为空返回 None。

`core/src/session/mod.rs:4161–4180,4474–4518`：完整上下文才调用 thread
contributors；有 reference_context_item 的普通 turn 只更新 world-state
与必要的 turn contributions，不重新读 memory 文件。

`memories/write/src/phase2.rs:406–472`：成功路径验证文件、确认租约、
提交基线、记账和指标，没有向当前前台 thread 推送新 memory 的调用。

结论：首次生成不是一个独立的注入触发事件。新文件可能在新会话或后续
完整上下文重建时自然被看到；不能据此说“生成后立刻注入”。

## compact 与 resume 的区别

`core/src/compact.rs:62–110,378–389`：DoNotInject 会清除 reference，
让下一正常 turn 重建完整初始上下文；BeforeLastUserMessage 在压缩结果
里直接重建。`compact_remote_v2.rs:324–335` 使用同一机制。
`compact_token_budget.rs:46–77` 通过 start_new_context_window 重建，
后者调用 `session/mod.rs:4430` 的完整上下文构造。都不是仅依赖压缩模型
碰巧把原摘要复述出来。

`core/src/session/mod.rs:1564–1578,1696–1758` 与
`core/src/session/rollout_reconstruction.rs:120–129,190–197,254–262`：
普通 resume 恢复原 baseline。若之前的 compaction 清除了 baseline，
则下一轮正常重建；并非每次 resume 都再注入。

Kimi 的 PostCompact（`agentExternalHooksService.ts:440–447`）只通知，
stdout 不直接进入模型。因此我们仍在下个 UserPromptSubmit 补入，而非
向正在继续运行的同一 turn 强行写入上下文。持续保留的插件系统规则允许
按需读取本地文件。这个宿主时机差异是明确边界，不新增引擎补丁。

reader receipt 记录 checked 与实际 injected：缺失摘要也完成一次检查；
普通 SessionStart 不重置；PostCompact 重置。checked 是唯一的完成检查
标志。正式版本升级保留该记录，不恢复开发期 receipt 的判断分支。

## Kimi 升级的真实机制

`apps/kimi-code/src/main.ts:163–180` 在解析子命令之前调用
maybeRelaunchWithStagedNativeUpdate，所以 kimi --version、web 与
__plugin_run_node 都不能被当成天然无更新副作用的入口。

`cli/update/native-swap.ts:434–443,517–529,570–640`：原生安装采用
旧 exe 改名到备份、新 exe 放到安装路径、再启动新进程的方式。运行中的
旧进程没有因此被热替换；Windows 仍使用旧映像的进程可能让备份暂时无法
删除，原生代码允许后续清理。npm 则由包管理器替换磁盘文件；不能保证
旧进程之后的延迟模块读取一定成功，失败由下一批重试处理。

NO_AUTO_UPDATE 阻止自动 staged payload，但 `manual=true` 的显式用户
更新仍会应用。我们不设置私有的 re-exec guard 来阻止它，也不接管用户
的 updater。若这类 re-exec 改变了 helper 注册 PID，当前批次可能超时
并重试；关闭时回收自有进程组/进程树，不额外做递归发现与重连状态机。

普通升级策略：保持可用连接、完成当前只读批次、结束自有 helper，下次
使用当前安装。不运行版本探针、不把产品版本差异当成失败、不热重启用户
服务。launcher hint 消失时回到 PATH；显式用户配置不存在则保留配置错误。

## 回归验证

reader 测试覆盖缺失/空摘要、首次发布后不插入、普通 resume 不重复、
compact 后重新读取、compact 后再 resume 不丢掉待恢复状态。
模拟宿主进程固定启动时版本，测试运行中安装变更后继续读、正常关闭后
启动新版本；同时证明没有 --version 探针或父进程环境修改。
另测安装暂时缺失仍借用健康服务、移除的 executable hint、子进程树回收。
六平台冻结包测试经过真实 Kimi 插件管理器和对应 shell launcher。
