"""HTTPS/OAuth endpoint for the Siyuan tools in this fork."""
import asyncio
import os
from urllib.parse import urlparse

import siyuan_mcp_server as upstream
import uvicorn
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.auth.routes import build_metadata, cors_middleware
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.responses import JSONResponse
from starlette.routing import Route

from oauth import PasswordOAuth


def build_server(provider):
    options = {
        "auth_server_provider": provider,
        "auth": AuthSettings(
            issuer_url=provider.base,
            resource_server_url=provider.resource,
            validate_token_resource=True,
            required_scopes=["siyuan"],
            client_registration_options=ClientRegistrationOptions(
                enabled=True, valid_scopes=["siyuan"], default_scopes=["siyuan"]
            ),
            revocation_options=RevocationOptions(enabled=True),
        ),
    }
    server = upstream._SiyuanMCPServer("siyuan", **options)
    writes = {"create_document", "update_block", "delete_block", "insert_block",
              "prepend_block", "append_block", "move_block", "push_message", "push_error_message"}
    for tool in asyncio.run(upstream.mcp.list_tools()):
        server.add_tool(
            getattr(upstream, tool.name), name=tool.name, description=tool.description,
            annotations=ToolAnnotations(
                readOnlyHint=tool.name not in writes,
                destructiveHint=tool.name in {"delete_block", "update_block", "move_block"},
                openWorldHint=False,
            ),
        )
    return server


if __name__ == "__main__":
    base = os.environ["SIYUAN_MCP_BASE_URL"].rstrip("/")
    provider = PasswordOAuth(base, os.environ["SIYUAN_MCP_PASSWORD"], os.environ["SIYUAN_MCP_DB"])
    server = build_server(provider)
    server.custom_route("/login", methods=["GET", "POST"])(provider.login)
    app = server.streamable_http_app(
        stateless_http=True, json_response=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=[urlparse(base).netloc, "127.0.0.1:*"],
            allowed_origins=[base, "https://chatgpt.com", "https://claude.ai"],
        ),
    )

    async def metadata(request):
        data = build_metadata(
            server.settings.auth.issuer_url, None,
            server.settings.auth.client_registration_options,
            server.settings.auth.revocation_options,
        ).model_dump(mode="json", exclude_none=True)
        # The SDK accepts public DCR clients; advertise that supported method.
        data["token_endpoint_auth_methods_supported"].append("none")
        data["revocation_endpoint_auth_methods_supported"].append("none")
        return JSONResponse(data, headers={"Access-Control-Allow-Origin": "*"})

    app.routes.insert(0, Route("/.well-known/oauth-authorization-server", metadata))
    app.routes.insert(0, Route("/revoke", cors_middleware(provider.revoke_request, ["POST", "OPTIONS"]), methods=["POST", "OPTIONS"]))
    uvicorn.run(app, host="127.0.0.1", port=16809, access_log=False)
