# ADR 0015：采用原生 hook 新版本提醒卡片

状态：接受。来源：用户比较纯UI通知、状态栏和原生hook方案后，明确
选择原生 hook 结果卡片，并授权实施、提交、推送和发布。

## 接口与范围

启用插件后默认运行。Kimi的UserPromptSubmit成功输出被直接渲染为
原生hook卡片，不需要模型生成提醒，同时也以user消息进入上下文。
用户已接受这个小型上下文影响；不虚构UI-only字段、不修改状态栏，
不通过stderr/错误/阻断强行显示，不伪装成官方Marketplace插件。

只提醒，不自动下载/安装插件或更新Kimi。文本由固定本地模板和校验
过的版本号组成，不使用远端release正文/名称，不把通知当成agent任务。
只给用户一个精确版本的原生安装命令，保留用户主动确认。

## 简单的后台与去重

独立短命check-updates进程每24小时最多尝试一次公开GitHub latest
release元数据请求。SessionStart/Stop/SessionEnd只做本地检查并
按需启动，不联网等待；不依赖生成worker是否关闭、暂停或出错。
不发送token、历史、prompt或用户标识，不使用Kimi模型和凭据。

前台只看有界本地缓存：正式稳定数字版本、新版大于当前版本、精确
仓库地址和已上传安装ZIP都成立才准备通知。每个数据目录只保留最近
已通知版本及一份短期pending记录，不为所有会话建立新数据库。

已准备不等于已显示；对应用户TurnStarted的prompt hash匹配后才
确认，其他hook阻断不消耗这次提醒。多个会话使用一个短期租约避免
同步刷屏；会话结束/压缩可释放，遗失会话超时后可重试。沿用已有
best-effort投递取舍，不保证exactly-once；不保存用户原文。

有更新时可以单独追加通知，即使当前记忆早已注入；不会重新发送
整个Memory Prompt。显示后不因/new、resume或compact反复提醒。

## 配置、故障与发布

updates.toml只有enabled这一项，默认true，false同时关闭检查与提醒。
它独立于reader.enabled和generation.enabled。无效设置只关闭通知；
网络、锁、缓存、进程或导入错误均不得丢弃已准备的记忆或阻止工作。

作为1.2.0发布，不覆盖旧Release或变更记忆schema/Prompt/来源格式。
提醒需要用户先安装一次具备此能力的版本，不可能远程赋予旧插件。
