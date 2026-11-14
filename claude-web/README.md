# Siyuan Notes

Search, read, summarize, create and edit Wenyuan's Siyuan notes through an
authenticated MCP connection. This plugin provides a workflow skill and a remote
Streamable HTTP server connection at https://siyuan-mcp.wenyuanxu.net/mcp.

Upload the Claude archive in Customize → Plugins, then connect the Siyuan service.
The connection uses OAuth with dynamic client registration and PKCE. On the
authorization page, review the client and callback address, then enter the MCP
connection password. The initial password matches the existing Siyuan web access
authorization code. The owner manages it as `SIYUAN_MCP_PASSWORD` with `sedit`.

Start with “Find my Siyuan notebooks” or “Search my notes for a keyword.” The
plugin can also apply edits requested by the owner and verify the resulting note.

For ChatGPT, add the server URL as a custom MCP server with OAuth authentication
at https://chatgpt.com/plugins and complete the OAuth authorization flow.

Build the Claude web archive from the repository root:

```sh
python3 claude-web/package.py
```

Upload `claude-web/dist/siyuan-notes-claude.zip`. Its root contains
`.claude-plugin/plugin.json`, `.mcp.json`, and `skills/siyuan/SKILL.md`.
Local Claude Code and Codex installation commands are in
[../local/README.md](../local/README.md).
