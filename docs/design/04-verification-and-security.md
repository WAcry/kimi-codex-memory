# DESIGN 04：验证、安全与边界

## 开发验证

```bash
uv sync --locked --group dev --default-index https://pypi.org/simple
npm ci --ignore-scripts --registry=https://registry.npmjs.org
npm run build:auth
uv run --no-sync python -m pytest -q
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
```

测试只使用临时 home、合成记录、本地模型/OAuth HTTP 服务。不得读取真实
用户历史或凭据，不得调用付费模型。设置 KIMI_MEMORY_NATIVE_KIMI 为已安装
Kimi 的绝对路径，可启用真实宿主集成测试；这些测试同样使用隔离的 home。

CI 在 Windows、macOS、Linux 的 x64/ARM64 上执行原生测试和冻结包测试。
发布包移到含空格及中文的目录后，移除 PATH 上的 Python/Node，验证 hook、
注入和 frozen worker。模拟服务验证三种模型接口、token 续期、401 恢复、
429 静默失败；模拟测试不能证明任意实际供应商的计费和模型质量。

## 认证

默认模型来自 Kimi 解析后的 /config 与当前本地配置中的凭据引用。配置值
不会被写入 Memory 配置。Kimi 的 oauth/kimi-code 等标识由原生语义映射到
credentials 下的存储名。

OAuthManager、FileTokenStorage、身份请求头等上游源码原样保存在 vendor/，
使用固定版本的构建依赖生成 native/auth.mjs。代码和许可证 hash 记录在
upstream.toml，CI 重建后核对 bundle。复用原生提前刷新、持久化、401 恢复
以及并发协调，而非另写一个竞争的 refresh-token 管理器。

原生 Windows OAuth 的跨进程协调本身是 best-effort；不能声称我们增强成了
严格的全系统事务。当前原生默认存储是 file，没有单独新增 keyring 或登录
系统。密钥只通过子进程管道进入当前请求，不保存到 Memory 的状态/日志。

401 对 subscription 只做一次原生强制刷新与重试；429 和其他额度错误不
触发交互、登录窗口或无界重试。

## 网络与工具

本地 Kimi API 一律绕过代理，保持认证和 loopback，不跟随重定向。云端模型
请求支持系统代理但同样拒绝重定向；不打印 HTTP body、完整历史和凭据。
模型端点需要 HTTPS，loopback 测试/本地 provider 可使用 HTTP。

合并只接触供应的记忆文件，工具没有任意 shell、网络或原始 session 访问。
限制越界路径和链接；Git 仅运行在专用的记忆暂存目录，禁用用户 Git hooks、
外部 diff 与全局配置。合并结果先验证再发布。

脱敏不是任意秘密检测器；用户仍需选择可信的模型服务。自动使用当前默认
provider 不意味着有权在后台改用其他供应商。

## 仍不实现

不支持旧 Kimi 日志协议、Gemini API、独立 keyring、完整媒体理解或引用 UI。
不自动更新 Kimi，不在 hook 中下载可执行更新，不承诺文件系统与数据库是
一个物理原子事务；使用发布意图与恢复流程补齐跨存储间隙。

Windows/macOS 的构建必须在相应 CI 真机环境验证，不能拿 Linux 的通过结果
当作所有平台已经验证。
