# 本机运行、轻量服务器远程管理

## 当前方案

- 本机运行 `hi～` 微信、消息采集器、控制页和已下载的 DeepSeek R1 8B。无需虚拟机，也不在轻量服务器运行模型。
- 服务器只承担 WireGuard 私网入口与在线状态中继。它不保存群名、聊天正文、摘要、媒体或提示词。电脑关机后，状态在 30 秒内变为离线；过期 60 秒的控制指令不会执行。
- 新群默认关闭。`text` 单群继续保留；多群 UIA 切换代码已加入，但未完成本机两群只读实测，`multi_group_verified=false` 时禁止多群发送。历史记录的存储和按群检索已就绪，微信页面回看与媒体解析尚未接入。
- 微信缩到系统托盘时，本机 UIA 已实测无法读消息。微信应保持登录、窗口不最小化，可放在其他程序后面。接入与发送不会移动鼠标；微信可能短暂获得焦点。暂不声称完全无焦点影响。

## 本机资源安排

主机 15.62 GiB 物理内存，在 2026-09-23 检查时只有 2.06 GiB 可用，而 R1 8B 尚未加载。先保持只有一个模型请求，近期上下文设较短，媒体处理在文字回复空闲时排队。运行时观察任务管理器的可用内存与 `ollama ps`；若出现持续换页或模型频繁卸载，切换到 HTTPS 模型 API 或升级到 32 GiB。不要为了部署助手再分配 Windows 虚拟机内存。

## 服务器上线前只读核对

登录 Ubuntu 后记录：`systemctl --type=service --state=running`、`ss -ltnup`、`free -h`、`df -h`、`ufw status verbose`、`ip addr`、注册网站服务和数据库备份方式。用网站原有测试账号在部署前后各完成一次注册流程。不要覆盖网站现有 Nginx、数据库、80/443 端口或工作目录。

助手中继使用独立目录 `/opt/wechat-assistant-relay`、独立系统用户、WireGuard UDP 端口，以及只绑定 WireGuard 地址的 TCP 8787。示例服务文件位于 `deploy/wechat-assistant-relay.service`，限制内存 128 MiB、CPU 20%。服务器 SQLite 只含 `agents` 和 `commands` 元数据表。

## 私网连接

先确认 SSH 公钥登录；不要把密码或私钥存入仓库。WireGuard 服务器作入口，本机主动连接，管理员设备作为另一对等端。控制页 8765 和中继 8787 只绑定各自的 WireGuard IP；防火墙不向公网开放这两个 TCP 端口。

服务器设置两个不同的 32 字符以上令牌：`ASSISTANT_AGENT_TOKEN`、`ASSISTANT_ADMIN_TOKEN`，以及 `ASSISTANT_WG_BIND` 和 `ASSISTANT_RELAY_DB`。令牌环境文件权限设为 `0600`。本机设置 `ASSISTANT_RELAY_URL=http://<服务器 WireGuard IP>:8787`、`ASSISTANT_AGENT_ID=home-pc`、`ASSISTANT_AGENT_TOKEN`，运行 `python -m remote.host_agent`。控制页可通过 `ASSISTANT_CONTROL_BIND=<本机 WireGuard IP>` 绑定，管理员连入私网后访问 `http://<本机 WireGuard IP>:8765`。现有 token 和同源检查仍生效。

## 验收顺序

1. 先在本机只读识别 `text` 和第二群，检查标题、会话切换、发送者、真正 @ 与普通消息；无误后设置 `multi_group_verified=true`，逐群开启发送。
2. 微信被遮挡、网络短暂中断以及助手重启时，重新建立消息基线，不补发旧 @；发送结果不确定时不自动重试。
3. 完成微信页面历史回看，显示实际读到的日期范围和缺口；中断后可续扫。旧 @ 不触发回复。
4. 媒体解析在本机排队，失败标记未知，文字回复优先。
5. 注册网站部署前后均可正常注册；服务器无聊天正文或媒体；电脑离线 30 秒后状态正确显示离线。

未完成对应实测前，不应把多群、历史回看或媒体解析标成已上线。
