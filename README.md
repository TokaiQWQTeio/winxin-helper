# 个人微信群 AI 助手

这个仓库包含消息处理、分群上下文、长期摘要、7 天原文清理、本机 DeepSeek 模型，以及基于 Windows 辅助功能的微信接入。**后台机器人默认停止，`config.json` 的自动发送为 `false`。新的发送方式不移动鼠标，但微信可能短暂获得焦点；多人群仍待实测。**

## 本机控制网页

在项目目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start-control.ps1
```

脚本在浏览器打开 `http://127.0.0.1:8765`。网页只监听本机地址，可以查看助手是否运行，手动启动或停止，以及在已下载的本机 `deepseek-r1:8b` 和兼容 OpenAI 聊天接口的 HTTPS API 之间切换。切换模型前需停止助手；API 密钥通过启动控制页时的环境变量提供，不会存入网页或 `config.json`。关闭网页或控制页终端不会自动停止已启动的后台助手；请使用页面上的“停止助手”，或运行 `scripts/stop-bot.ps1`。

启动前页面会要求确认焦点提示。程序不移动鼠标，只在电脑连续空闲约 10 秒后尝试发送；微信仍可能短暂抢到焦点，恢复原窗口的效果尚未在持续模式实测。只回复 `text` 白名单群中的真正 @；第三位群成员的识别尚未验证。默认不会自动启动，也不会因访问网页发送微信消息。

## 接入与已验证结果

专用助手微信号已在这台电脑登录，并建立了 `text` 测试群。当前微信版本为 4.1.13.65。Windows UI Automation 能读取群标题与消息控件；真正 @ 的消息有 U+2005 分隔符，独立的会话提示还会显示 `[有人@我]`。程序同时要求这两个信号与发送者、消息正文匹配。最新 @ 的发送者从微信会话列表读取；其他可见消息可用窗口捕获和 OCR 收集。仍缺少第三位成员的真实样本。程序不读取微信数据库或进程内存。

已在 `text` 群用 `hi～` 账号发送一次固定测试消息“AI助手发送通道测试，请忽略”，并确认消息出现在群内、输入框清空。当前微信版本不响应发送按钮的后台辅助功能 Invoke 调用；实测可短暂切到前台，核对群和草稿后点击发送，再恢复原窗口。群聊 @ 问答的目标流程和验收条件见 [设计方案](docs/design.md)。

2026-09-23 的问答预览确认：TokaiTeio 在 `text` 群真正 @ `hi～` 提问“你好”，程序识别发送者和 @ 信号，本机 `deepseek-r1:8b` 生成“你好！有什么可以帮你的吗？”。用户随后授权发送这一条，发送器确认它出现在 `text` 群且输入框清空。经用户授权的 `run-once` 单次联调和后台持续监听也各成功回复一次；数据库有两条 `sent` 投递记录，持续模式运行中没有重复发送。

## 配置

1. 复制 `config.example.json` 为 `config.json`，填写助手在群内的昵称、测试群名、HTTPS API 地址和模型名。`config.json` 已加入 `.gitignore`。
2. 当前本机 `config.json` 已选择免费的本机 DeepSeek R1 8B 模型：`http://127.0.0.1:11434/v1`、`deepseek-r1:8b`。它通过 Ollama 在本机运行，不需要 API 密钥。若改用云端 HTTPS 接口，在 PowerShell 中设置模型密钥：`$env:WECHAT_AI_API_KEY = '你的密钥'`；程序不会保存密钥。DeepSeek 官方云端 API 按 token 收费，网页版免费聊天不能直接当作机器人 API 使用。
3. 运行 `python -m wechat_ai --config config.json check-config` 检查配置。请先启动 Ollama 并下载 `deepseek-r1:8b`，再进行本地模型测试。

本仓库已经把 Ollama 便携版解压到忽略目录 `runtime/ollama`。首次安装本机模型时，在项目目录的普通 PowerShell 中运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup-local-model.ps1
```

脚本会让 Ollama 只监听 `127.0.0.1:11434`，把模型保存在 `runtime/models`，下载约 5.2 GB 的 `deepseek-r1:8b`，然后执行一次不接触微信的模型问答测试。日后运行 `scripts/start-bot.ps1` 会自动启动本机模型。首次启动会在当前 Windows 用户的 `.ollama` 目录生成 Ollama 自己的本机密钥文件。

`auto_send_enabled` 起初保持 `false`。本机模型和 `text` 群的单次自动回复实测成功后，用户授权将这个测试群的持续回复开启。`config.json` 仍只包含 `text` 群；第三位成员的识别尚待实测。

在 `text` 群的单次自动联调成功后，用户授权只为这个测试群开启持续回复。用户随后指出模拟点击会操纵鼠标，因此已停止后台进程、关闭自动发送，并移除了实际鼠标点击发送。后台投递测试已确认窗口消息方式不移动光标且能发送，但会抢到焦点；网页提供空闲等待和启动前确认，焦点恢复仍需真实联调。添加第三位群成员后仍需再做一次真实 @ 验证。

## 现有命令

- `python -m wechat_ai probe`：只读检查微信进程、版本和接入认证状态。
- `python -m wechat_ai --config config.json simulate events.jsonl`：用模拟事件演练白名单、去重和回复逻辑。使用预览模型及预览发送器，既不访问模型 API，也不发送微信消息，不写入正式数据库。
- `python -m wechat_ai --config config.json maintenance`：先更新群摘要，再删除超过 7 天的原文；后台持续监听时每 24 小时自动执行一次。
- `python -m wechat_ai --config config.json clear-summary "群名"`：清除指定群的长期摘要。
- `python -m wechat_ai capture-ui`：对**当前可见的微信窗口**截图并离线 OCR，结果写入 `data/diagnostics`。它可能包含屏幕上的聊天内容；只应在助手账号登录并打开测试群后使用。需先安装 `pip install -r requirements-ui.txt`。
- `python -m wechat_ai probe-uia`：只读查询微信暴露给 Windows 辅助功能接口的控件。即使微信在后台也可尝试；结果可能包含可见聊天内容，同样保存在 `data/diagnostics`。
- `.venv\Scripts\python -m wechat_ai --config config.json watch-preview`：只读预览首个白名单群的新文本消息、候选 @ 和可识别的发送者。后台截图通过独立进程获取，OCR 只截取消息旁的昵称区域，截图随后删除。不会调用模型或发送。启动时把已有消息作为基线；仍需要多人样本核对，按 Ctrl+C 停止。
- `.venv\Scripts\python -m wechat_ai --config config.json watch-model-preview`：收到新的真正 @ 后识别发送者，调用本机 DeepSeek，并只在终端打印预览回复。不会向微信发送；启动前的旧消息作为基线，按 Ctrl+C 停止。
- `python -m wechat_ai --config config.json run`：持续监听和回复入口；当前仅为 `text` 群启用。
- `python -m wechat_ai --config config.json run-once`：单次联调命令。启动后只处理下一条确认的真正 @，尝试发出一条模型回复，然后自行退出；要求配置恰好一个白名单群。手动启动这个命令意味着允许它在该群发送这一条回复。
- `python -m wechat_ai --config config.json test-model`：只调用已配置模型做一句离线问答，不读取或发送微信消息。

模拟事件每行一个 JSON 对象，例如：

```json
{"group":"测试群名称","sender":"张三","text":"@小助手 你好","source_id":"test-1","received_at":"2026-09-22T10:00:00+08:00","is_self":false,"mention_verified":true}
```

`mention_verified` 必须由经过真实群聊测试的微信接入器给出。仅有文字 `@小助手` 不足以设置该字段为 `true`。

## 实时接入验证清单

1. 已在两人测试群验证真正 @ 与手打 `@昵称` 的区别，及后台新消息监听。
2. 需要第三位成员在测试群发消息，验证不同发送者的昵称识别及与消息正文的配对。
3. 已用固定测试消息、单独授权的模型回复、`run-once` 和后台持续监听验证发送与结果确认；当前仅在 `text` 群启用。
4. 仍需真实多人群、模型故障、群间隔离及微信重启后的行为测试，再扩大使用范围。

如果界面无法可靠区分真正 @ 或无法核实目标群与发送结果，停止机器人检查。不能以读取数据库、进程内存或仅匹配 `@昵称` 文字来绕过该关卡。

## 测试

```powershell
python -m unittest discover -s tests -v
```
