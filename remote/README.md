# 远程 HTTPS MCP / OAuth 服务

此目录运行服务器端 Python 服务：OAuth 动态注册、PKCE、登录页、Token
持久化和 HTTPS MCP 适配。Nginx 将 HTTPS 请求转发到此服务。
`src/siyuan_mcp_server/` 提供共用的思源工具实现。

当前部署：`ssh oracleg`，`/home/ubuntu/siyuan/mcp/siyuan-mcp-server/remote`。
公网入口：`https://siyuan-mcp.wenyuanxu.net/mcp`。
服务监听 `127.0.0.1:16809`，思源 API 监听 `127.0.0.1:6806`。

## 安装

```sh
cd /home/ubuntu/siyuan/mcp
git clone https://github.com/wyxu95/siyuan-mcp-server.git
cd siyuan-mcp-server/remote
uv sync --locked
```

服务环境文件为 `/home/ubuntu/siyuan/mcp/credentials.env`，权限 600：

```sh
SIYUAN_API_URL=http://127.0.0.1:6806
SIYUAN_API_TOKEN=YOUR_SIYUAN_API_TOKEN
SIYUAN_MCP_BASE_URL=https://siyuan-mcp.wenyuanxu.net
SIYUAN_MCP_PASSWORD=YOUR_MCP_CONNECTION_PASSWORD
SIYUAN_MCP_DB=/home/ubuntu/siyuan/mcp/state/oauth.sqlite3
```

密钥源由所有者在 `~/linux_dotfiles/secrets.env.age` 中使用 `sedit` 管理，
将对应值同步到服务环境文件，再重启服务。初始 MCP 连接密码与现有思源
网页访问授权码相同。轮换思源 API Token 时同步更新思源本身的设置。
OAuth 数据库所在的 `state/` 目录权限为 700，数据库文件权限为 600。

当前 systemd 配置见 `siyuan-mcp.service`，Nginx 配置见 `nginx.conf`：

```sh
sudo cp siyuan-mcp.service /etc/systemd/system/
sudo cp nginx.conf /etc/nginx/conf.d/siyuan-mcp.wenyuanxu.net.conf
sudo systemctl daemon-reload
sudo systemctl enable --now siyuan-mcp
sudo nginx -t
sudo systemctl reload nginx
```

Cloudflare A 记录指向 `130.61.100.223`，DNS only。
证书位于 `/etc/letsencrypt/live/siyuan-mcp.wenyuanxu.net/`，
由 Certbot 使用已有 Cloudflare DNS 凭据自动续期，并重载 Nginx。

更新代码后运行 `uv sync --locked` 并重启服务。保留环境文件和
`state/oauth.sqlite3` 即可保留密钥和已有授权。

## 运维与验证

### 内容与访问范围

读取工具返回完整原文，包括邮箱、链接、路径、属性和凭据。文件 Base64 工具支持原始二进制附件。

| 客户端 | 后缀 `(-NB)` | 后缀 `(-NM)` | 其他笔记本 |
| --- | --- | --- | --- |
| Codex CLI、Claude CLI | 可访问 | 禁用 | 可访问 |
| ChatGPT、Claude 网页版 | 禁用 | 禁用 | 可访问 |

在思源中为笔记本名称添加后缀即可设置权限，例如 `Alibaba(-NM)`、`Diary(-NB)`。每次调用都读取当前笔记本名称，改名后下次调用生效。后缀按表中大小写与括号精确匹配。

`SIYUAN_CLI_CLIENT_IDS` 保存已授权的 CLI OAuth 客户端 ID，以逗号分隔；重新注册 CLI 时将新 ID 加入该配置并重启。其他 HTTPS 客户端使用网页版范围。本地 stdio 使用 CLI 范围。
规则覆盖搜索、SQL、块操作和文件/附件。SQL 查询在投影、聚合和子查询前按笔记本过滤；文件工具读取有权限的文档及其索引附件。

### Cloudflare 主页

`https://siyuan-mcp.wenyuanxu.net/homepage/mcp` 提供单一只读工具 `get_homepage`。`SIYUAN_HOMEPAGE_DOC_ID` 指定公开主页，`SIYUAN_HOMEPAGE_TOKEN` 是该入口的独立 Bearer Token；同一 Token 配置在 Cloudflare Pages 项目 `homepage` 的生产环境 Secret。工具返回 Markdown 及正文引用附件的 Base64；传入上次 `revision` 时，内容相同会返回 `unchanged`。

主页由 `wyxu95/homepage` 中的“发布主页”思源插件手动发布。桌面端和服务器浏览器端都导出当前文档及图片，提交到 `https://wenyuanxu.net/api/homepage/publish`；Cloudflare Pages Functions 完成排版，Worker `wenyuan-homepage-publication` 的 Durable Object 保存统一发布版本。插件提示成功后，访客刷新即可读取新版本，草稿在下一次点击发布时更新。

发布接口的独立密钥 `HOMEPAGE_PUBLISH_TOKEN` 同时保存在本服务环境文件与 Pages 项目生产 Secret。每个思源实例的插件设置位于 `data/storage/petal/siyuan-homepage-publisher/config.json`。当前 Windows 本地与服务器均已安装并启用；安装包为 `https://wenyuanxu.net/downloads/siyuan-homepage-publisher.zip`。只读主页 MCP 入口继续供已授权工具使用。

```sh
sudo systemctl status siyuan-mcp --no-pager
sudo journalctl -u siyuan-mcp -n 50 --no-pager
uv run --locked python -m unittest -v test_oauth
```

访问 Token 有效期一小时，刷新 Token 为三十天；刷新时轮换并撤销旧 Token。
撤销接口同时撤销配对 Token。登录页检查 Origin 和 CSRF cookie，
登录与注册端点由 Nginx 限速。

## ChatGPT 网页版

在 <https://chatgpt.com/plugins> 选择 **Add custom MCP server**，填写
`https://siyuan-mcp.wenyuanxu.net/mcp`，认证选 **OAuth**，使用动态注册
（DCR），然后 **Create as a plugin** 并完成登录。OAuth discovery 提供
端点信息，scope 为 `siyuan`，PKCE 为 `S256`。

官方步骤：<https://developers.openai.com/plugins/deploy/connect-chatgpt>。

Claude 网页插件见 [../claude-web/README.md](../claude-web/README.md)。
