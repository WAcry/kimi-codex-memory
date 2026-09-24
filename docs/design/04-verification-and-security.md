# DESIGN 04：验证、安全与当前边界

## 默认开发验证

```bash
uv sync --locked --group dev --default-index https://pypi.org/simple
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
uv build
```

默认测试使用独立临时 home、合成会话、内存脚本模型和本机假 HTTP 服务，
不读取用户会话，不使用真实凭据，不调用付费模型。测试需覆盖读路径的
禁止导入依赖、损坏生成配置／数据库、未知 API、分页和身份、引用、租约、
过期、notes、发布中断、只读工具路径边界及真实插件入口。

## 原生 Kimi 集成验证

```bash
KIMI_MEMORY_NATIVE_KIMI=/absolute/path/to/kimi \
  .venv/bin/python -m pytest tests/test_server.py -q
```

这是明确 opt-in 的本机集成测试。它创建测试专属 Kimi home，移除模型凭据
环境，关闭遥测；启动真实二进制的原生服务器，验证连接和借用生命周期。

历史测试仅在测试目录内创建空 session 并注入合成 wire fixture，然后通过
真实 cold transcript API 读取问题、答案和 assistant 引用。模型部分仍然
使用脚本替身。该测试曾发现 registry ID 与 API ID 不一致，不能被 mock-only
测试替代。

真实模型的摘要质量、复杂长会话表现、不同供应商的计费／限流，以及完整
TUI/Web 的视觉引用呈现，不在这些无成本测试的证明范围内。

## 凭据

支持显式环境变量凭据，或用户明确选中的 Kimi provider 配置。配置文件中的
内联 key 不复制到本项目配置；文件型 OAuth 只读取尚未过期的 access token。
不刷新 refresh token，不支持 keyring，不主动变更用户的认证状态。

模型端点默认需要 HTTPS；仅 loopback 测试服务允许明文 HTTP。禁用自动
重定向和隐式 HTTP 代理，避免认证头和历史被带到意外目的地。这也意味着依赖
环境 HTTP_PROXY 的网络部署需要显式设计支持，而不能假设已有代理自动生效。

错误诊断不包含 HTTP body、密钥或完整历史。尽力脱敏覆盖常见密钥、Bearer、
JWT、私钥块和带凭据的 URL，但不是任意秘密检测器。保存用户自己的 notes
本来就可能含敏感文字，最终责任仍包括可信模型和项目范围选择。

## 权限与文件

新目录和文件采用私人权限；不自动 chmod 用户已有文件以绕过安全检查。
合并工具不能读绝对路径、..、越界链接、Git 元数据或未供应的原始日志。
只写一个候选摘要，宿主程序负责发布。Git 操作只在项目运行数据的临时工作
区中执行，不重置源代码仓库。

后台 helper 不是安全沙箱中的只读服务器；它是完整 Kimi 服务。因此只绑定
loopback，保留认证，并仅由客户端选择只读历史请求。无需对外开放端口。

## 有意不实现

- Windows 的文件锁／链接替代；旧 Kimi 协议和自有完整 JSONL reader。
- 媒体二进制理解、原始聊天的第二份存储、向量检索服务。
- 原生引用 UI、强制模型百分之百引用、语义级引用证明。
- 自行刷新 Kimi OAuth、安装／升级 Kimi、无限常驻的服务监督器。

这些边界必须写在对用户的行为说明中；不能把配置失败隐藏成生成成功。
