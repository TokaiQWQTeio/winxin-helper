# 本机虚拟机与轻量服务器部署记录

## 当前状态

代码已提供本机逐群登记和开关、多群会话辅助功能切换、历史导入的本地存储结构，以及仅传输在线状态与控制指令的轻量中继。**尚未部署虚拟机、WireGuard 或服务器服务。**多群切换代码尚未在隔离虚拟机中取得真实微信样本验证；30 天页面回看与媒体解析也尚未接入。在此之前 `dedicated_vm=false`，发送入口拒绝同时启用多个群。网页上添加新群默认关闭。

现有 `text` 群数据仍在本机 `data/assistant.db`，没有迁往服务器。安装前需备份 `config.json` 与 `data/assistant.db`；不要将它们提交到 GitHub。

## 服务器上线前只读核对

登录 Ubuntu 后记录：`systemctl --type=service --state=running`、`ss -ltnup`、`free -h`、`df -h`、`ufw status verbose`、`ip addr`、注册网站服务与数据库备份方式。用网站原有测试账号完成一次注册流程，记录结果。不要覆盖网站现有 Nginx、数据库、80/443 端口或工作目录。

服务器上的助手组件只需要独立目录 `/opt/wechat-assistant-relay`、独立系统用户、WireGuard UDP 端口与仅绑定 WireGuard 地址的 TCP 8787。`remote/status_service.py` 只接受 agent ID、在线状态、任务状态及 `start/stop/pause/resume`，拒绝其他字段；数据库表不包含群名、正文、媒体和提示词。离线阈值为 30 秒；过期 60 秒的指令不执行。

## 认证和网络

先为服务器添加可审计的 SSH 公钥，确认密钥登录后再部署。不要把 SSH 密码、私钥或 WireGuard 私钥发到聊天或提交到仓库。WireGuard 服务器作为入口，虚拟机主动连接；远程管理员设备作为另一对等端。为每个对等端分配单独的私有 IP 和密钥，防火墙只开放选定的 WireGuard UDP 端口。TCP 8765 控制页和 8787 中继只在 WireGuard 地址上监听；防火墙不向公网开放它们。

设置两枚不同的 32 字符以上令牌：`ASSISTANT_AGENT_TOKEN` 供虚拟机上报状态、接收和确认指令，`ASSISTANT_ADMIN_TOKEN` 供管理员读取状态和提交指令。服务器服务另需 `ASSISTANT_WG_BIND`、`ASSISTANT_RELAY_DB`。在虚拟机设置 `ASSISTANT_RELAY_URL=http://<服务器 WireGuard IP>:8787`、`ASSISTANT_AGENT_ID=vm1`，运行 `python -m remote.vm_agent`。控制页通过 `ASSISTANT_CONTROL_BIND=<虚拟机 WireGuard IP>` 绑定后，管理员连入 WireGuard 访问 `http://<虚拟机 WireGuard IP>:8765`。控制页现有 token 和同源检查仍生效。

令牌环境文件应仅供独立服务用户读取（权限 `0600`）；中继数据库目录应仅供该用户写入。服务器进程设置内存上限，按实际网站余量选择，建议上线前测量再定。中继不运行模型或微信。

## 虚拟机准备

当前没有 Windows ISO/现成虚拟机。准备合法 Windows 安装介质后，先只读安装微信和采集器，不启用自动发送。虚拟机窗口中微信保持登录且可读取；宿主机独立运行 Ollama。现有配置只接受本机 HTTP 或 HTTPS 模型地址，因此虚拟机需要经过受限的本地 SSH 隧道把其 `127.0.0.1:11434` 转发到宿主机的 `127.0.0.1:11434`；该隧道尚未安装。模型接口不得暴露到公网。先在虚拟机内核对 `text` 和另一群的标题、会话切换、发送者与真正 @ 信号，再设置 `dedicated_vm=true` 并逐群开启发送。媒体任务需要单独排队，在文字回复空闲时处理。

## 验收顺序

1. 注册网站部署前后各完成一次同样的注册测试；确认网站端口与资源使用正常。
2. 服务器 SQLite schema 只有 `agents`、`commands`；检查日志与目录内无群消息或媒体。
3. 停止虚拟机后 30 秒内，服务器状态报告 `offline`；恢复后旧 @ 只重建基线，不补发。
4. 两个新群先只读观察，再逐群打开回复；验证普通消息不发送、真正 @ 各自回复、上下文不串群。
5. 历史任务显示实际读到的范围和缺口；中断后可续扫，旧 @ 永不自动发送；媒体失败显示未知。

没有完成第 4、5 项前，不应把多群、历史回看和媒体解析标成已上线。
