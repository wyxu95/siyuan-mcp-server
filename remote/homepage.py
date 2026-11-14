"""Read-only MCP resource for the owner's public homepage."""
import base64
import hashlib
import mimetypes
import os
import re
import secrets
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

import requests
import siyuan_mcp_server as upstream
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations


class HomepageTokenVerifier(TokenVerifier):
    def __init__(self, token, resource):
        self.token, self.resource = token, resource

    async def verify_token(self, token):
        if secrets.compare_digest(token, self.token):
            return AccessToken(token=token, client_id="cloudflare-homepage",
                               scopes=["homepage:read"], resource=self.resource)
        return None


def get_homepage(revision: str = "") -> dict:
    """Read the configured public document and its referenced assets, with original URLs.

    Pass the previous revision to omit unchanged content and assets.
    """
    document_id = os.environ["SIYUAN_HOMEPAGE_DOC_ID"]
    content = upstream._post_to_siyuan_api(
        "/api/export/exportMdContent", {"id": document_id})["content"]
    current = hashlib.sha256(content.encode()).hexdigest()
    if current == revision:
        return {"revision": current, "unchanged": True}
    assets = {}
    for match in re.finditer(r'''(?:\]\(|(?:src|href)=["'])(assets/[^\s)"'<>]+)''', content):
        reference = match[1]
        path = PurePosixPath(unquote(reference))
        if ".." in path.parts or path.parts[0] != "assets" or "\\" in str(path):
            raise ValueError("Invalid homepage asset path")
        upstream.check_file("/data/" + str(path), upstream._raw_post_to_siyuan_api)
        url, headers = upstream._get_siyuan_request_parts("/api/file/getFile")
        response = requests.post(url, headers=headers, json={"path": "/data/" + str(path)}, timeout=20)
        response.raise_for_status()
        if response.headers.get("Content-Type", "").startswith("application/json"):
            raise ValueError("Homepage asset is unavailable")
        if len(response.content) > 5 * 1024 * 1024:
            raise ValueError("Homepage assets must be at most 5 MiB each")
        assets[reference] = {
            "type": mimetypes.guess_type(str(path))[0] or "application/octet-stream",
            "base64": base64.b64encode(response.content).decode(),
        }
    return {"revision": current, "markdown": content, "assets": assets}


def build_homepage_app(base):
    resource = base + "/homepage/mcp"
    server = MCPServer(
        "public-homepage",
        token_verifier=HomepageTokenVerifier(os.environ["SIYUAN_HOMEPAGE_TOKEN"], resource),
        auth=AuthSettings(issuer_url=base, resource_server_url=resource,
                          validate_token_resource=True, required_scopes=["homepage:read"]),
    )
    server.add_tool(get_homepage, annotations=ToolAnnotations(
        readOnlyHint=True, destructiveHint=False, openWorldHint=False))
    return server.streamable_http_app(
        stateless_http=True, json_response=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=[urlparse(base).netloc, "127.0.0.1:*"], allowed_origins=[base]),
    )
