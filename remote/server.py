"""HTTPS/OAuth endpoint for the Siyuan tools in this fork."""
import asyncio
import os
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import siyuan_mcp_server as upstream
import uvicorn
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.auth.routes import build_metadata, cors_middleware
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.applications import Starlette
from starlette.routing import Mount, Route

from oauth import PasswordOAuth
from homepage import build_homepage_app
from siyuan_mcp_server.access import web_client


class ClientAccessMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, provider, cli_client_ids):
        super().__init__(app)
        self.provider, self.cli_client_ids = provider, cli_client_ids

    async def dispatch(self, request, call_next):
        authorization = request.headers.get("Authorization", "")
        token = None
        if authorization.startswith("Bearer "):
            token = await self.provider.load_access_token(authorization[7:])
        context = web_client.set(not (token and token.client_id in self.cli_client_ids))
        try:
            return await call_next(request)
        finally:
            web_client.reset(context)


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
    shared_client_ids = {value for value in os.environ.get("SIYUAN_SHARED_REFRESH_CLIENT_IDS", "").split(",") if value}
    provider = PasswordOAuth(base, os.environ["SIYUAN_MCP_PASSWORD"], os.environ["SIYUAN_MCP_DB"], shared_client_ids)
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
    app.add_middleware(ClientAccessMiddleware, provider=provider,
                       cli_client_ids=set(os.environ.get("SIYUAN_CLI_CLIENT_IDS", "").split(",")) | shared_client_ids)
    if os.environ.get("SIYUAN_HOMEPAGE_TOKEN"):
        owner_app = app
        homepage_app = build_homepage_app(base)

        @asynccontextmanager
        async def lifespan(application):
            async with owner_app.router.lifespan_context(owner_app), homepage_app.router.lifespan_context(homepage_app):
                yield

        app = Starlette(routes=[Mount("/homepage", homepage_app), Mount("/", owner_app)], lifespan=lifespan)
    uvicorn.run(app, host="127.0.0.1", port=16809, access_log=False)
