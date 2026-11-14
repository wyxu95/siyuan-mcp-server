# 本地 Claude Code / Codex

服务器地址：`https://siyuan-mcp.wenyuanxu.net/mcp`。

## Claude Code

```sh
claude mcp add --scope user --transport http siyuan https://siyuan-mcp.wenyuanxu.net/mcp
claude mcp login siyuan
```

## Codex

```sh
codex mcp add siyuan --url https://siyuan-mcp.wenyuanxu.net/mcp
```

Codex 检测到 OAuth 时会引导登录。后续单独登录可运行：

```sh
codex mcp login siyuan
```

登录时在思源 MCP 授权页核对客户端和回调地址，然后输入 MCP 连接密码。
初始密码与现有思源网页访问授权码相同，由服务所有者通过
`SIYUAN_MCP_PASSWORD` 管理。客户端保存各自的 OAuth 授权。

SSH 或无浏览器环境可运行 `codex mcp login siyuan --no-browser` 或
`claude mcp login siyuan --no-browser`，在可用的浏览器中完成授权后，
按终端提示粘贴完整回调地址。

验证连接：

```sh
codex mcp list
claude mcp get siyuan
```

## 独立客户端账号

第二个 Claude 账号使用对应的配置目录：

```sh
CLAUDE_CONFIG_DIR="$HOME/.claude-uni" claude mcp add --scope user --transport http siyuan https://siyuan-mcp.wenyuanxu.net/mcp
CLAUDE_CONFIG_DIR="$HOME/.claude-uni" claude mcp login siyuan
```

`ucodex`、`scodex`、`qcodex` 的独立配置可使用相应 `CODEX_HOME`：

```sh
CODEX_HOME="$HOME/.local/state/ucodex/home" codex mcp add siyuan --url https://siyuan-mcp.wenyuanxu.net/mcp
```

## Dotfiles 共享定义

`~/linux_dotfiles/mcp/servers.json` 保存共享服务地址，`mcp-sync` 将共享条目
合并到各客户端配置，客户端自己的其他 MCP 条目由各客户端管理。
标准 `mcp add` 命令也可以直接安装这个 HTTPS 服务。
