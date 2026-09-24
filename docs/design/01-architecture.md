# DESIGN 01：架构与失败边界

本文件解释实现选择，不替代 `../adr/` 中的用户决策。

## 两条运行路径

```text
UserPromptSubmit → reader.py → v2 阅读规则 + 已发布 memory_summary.md
           │                      │
           └──────────→ 前台 agent 自己 rg/Grep/Read

SessionStart / TurnStarted / Stop / SessionEnd
           │
           └→ 元数据通知队列 → 独立 worker 进程
                    │
                    ├→ Kimi 当前 transcript API → 引用同步
                    ├→ 闲置来源 → 无工具提取模型 → SQLite 摘要
                    └→ 选集 + 文件 diff → 受限合并模型 → 原子发布
```

reader 和 hook 渲染不导入 `config`、`store`、`http`、`kimi`、`models` 或 `worker`。
CLI 对各功能使用延迟导入，避免 worker 的语法／依赖错误阻断 `render` 或 `hook`。
读取配置独立，最近一次有效配置提供本地回退；即使 SQLite 不可读，文件仍可读。
manifest 不声明 systemPrompt、systemPromptPath、sessionStart.skill 或
skillInstructions，避免静态/动态内容重复，也不依赖自定义 profile 是否
包含 plugin_sections。无操作时 stdout 必须为空，不能输出 JSON 空对象。

Python 3.11+ 标准库覆盖 TOML、SQLite、HTTP、子进程、文件和 JSON。发布包
自带 Python 运行环境；终端用户不需要 Python 或 pip。Windows 使用 msvcrt
锁、进程树回收与原子文件替换，不依赖 POSIX 权限位或符号链接。
OAuth 的原生 Kimi 源码单独打包，由已经安装的 Kimi 的 Node 运行时执行。

## 代码职责

| 模块 | 职责 |
| --- | --- |
| `reader`, `hooks` | 本地读取、注入判定、短通知与独立唤醒 |
| `config`, `cli` | 分离配置、用户命令与诊断 |
| `server`, `http`, `kimi` | 原生服务管理、认证、界面契约与分页 |
| `evidence`, `citations` | 证据来源、预算、尽力脱敏、引用解析 |
| `store` | 摘要元数据、租约、引用收据与发布意图 |
| `models`, `model_config`, `responses`, `oauth` | 默认模型解析、三种协议与原生 OAuth 桥接 |
| `platform` | Windows/POSIX 锁之外的进程、可执行文件和 npm shim 边界 |
| `worker` | 引用同步、提取、合并和危险操作门禁 |
| `workspace` | 文件物化、diff、受限工具与发布恢复 |

## 磁盘布局

```text
<memory-home>/
  reader.toml
  worker.toml
  reader-last-good.json
  worker-status.json
  state.sqlite
  worker.lock
  injections/<session-hash>.json
  activity/<session-hash>.json
  queue/<time-random>.json
  current.json                   原子切换的 generation 指针
  memories_v2/
    extensions/ad_hoc/notes/
  _staging/<generation-id>/
  _generations/<generation-id>/
    memory_summary.md
    rollout_summaries/
    extensions/                  本次合并所见的快照
    phase2_workspace_diff.md
    _manifest.json
    .git/                        内部单提交基线
```

稳定 notes 目录不随发布指针切换。生成目录保存的仅是摘要与 notes 快照，不是
完整原始对话。引用收据包含事件指纹、来源 ID 和使用时间，不包含回答正文。
reader 注入不可变 generation 的路径；近期会话引用的 generation 暂不清理。
current.json 是唯一发布入口；缺失时表示尚未发布，不读取其他目录猜测
摘要。程序发布版本与数据库及文件格式版本独立，正式基线见 ADR 0007。

注入状态和扫描状态都不是记忆真实性的依据，只用于减少重复工作。读者每次
自行读取本地文件，不向 worker 请求摘要。

## 故障状态

生成关闭、API 失败、兼容性拒绝、模型失败等状态写入 `worker-status.json`。
`reader_available` 表示设计上读取未被关闭，不是保证磁盘永不损坏。文件本身
丢失或用户主动关闭 reader，是另一类问题。

模型失败保留最后发布版本。引用同步不完整时，不能用“本次没有看到使用”
作为过期证据。生成请求错误不允许通过 hook exit code 2 阻断前台。

默认是机会式唤醒，不承诺关闭所有 Kimi 进程后仍有精确定时任务。一个短期
worker 合并已到达的通知，使用每-home 文件锁避免多个生成实例竞争。
