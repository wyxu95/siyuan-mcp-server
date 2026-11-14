"""Single-owner OAuth provider; the MCP SDK handles DCR, PKCE and token routes."""
import hashlib
import html
import json
import secrets
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse

from mcp.server.auth.provider import (
    AccessToken, AuthorizationCode, AuthorizationParams, AuthorizeError,
    OAuthAuthorizationServerProvider, RefreshToken, TokenError, construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from mcp.server.auth.middleware.client_auth import AuthenticationError, ClientAuthenticator
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse


class PasswordOAuth(OAuthAuthorizationServerProvider):
    def __init__(self, base, password, database):
        self.base, self.resource, self.password = base, base + "/mcp", password
        Path(database).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(database)
        Path(database).chmod(0o600)
        self.db.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT, key TEXT, data TEXT, expires REAL, PRIMARY KEY(kind,key))")

    def save(self, kind, key, data, expires):
        with self.db:
            self.db.execute("DELETE FROM records WHERE expires < ?", (time.time(),))
            self.db.execute("INSERT OR REPLACE INTO records VALUES (?,?,?,?)", (kind, key, json.dumps(data), expires))

    def load(self, kind, key):
        row = self.db.execute("SELECT data FROM records WHERE kind=? AND key=? AND expires>?", (kind, key, time.time())).fetchone()
        return json.loads(row[0]) if row else None

    def take(self, kind, key):
        # Atomic consumption prevents concurrent code/refresh-token replay.
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            data = self.load(kind, key)
            self.db.execute("DELETE FROM records WHERE kind=? AND key=?", (kind, key))
        return data

    async def get_client(self, client_id):
        data = self.load("client", client_id)
        return OAuthClientInformationFull.model_validate(data) if data else None

    async def register_client(self, client_info):
        self.save("client", client_info.client_id, client_info.model_dump(mode="json"), time.time() + 365 * 86400)

    async def authorize(self, client, params):
        if params.resource not in (None, self.resource):
            raise AuthorizeError("invalid_target", "Use the Siyuan MCP resource URL")
        pending = secrets.token_urlsafe(32)
        self.save("pending", pending, {
            "client_id": client.client_id, "params": params.model_dump(mode="json"),
            "csrf": secrets.token_urlsafe(32),
        }, time.time() + 600)
        return self.base + "/login?" + urlencode({"request": pending})

    async def load_authorization_code(self, client, authorization_code):
        data = self.load("code", authorization_code)
        return AuthorizationCode.model_validate(data) if data else None

    def issue(self, client_id, scopes, resource):
        now = int(time.time())
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        common = dict(client_id=client_id, scopes=scopes, resource=resource, subject="wenyuan")
        self.save("access", access, AccessToken(token=access, expires_at=now + 3600, **common).model_dump(), now + 3600)
        self.save("refresh", refresh, RefreshToken(token=refresh, expires_at=now + 30 * 86400, **common).model_dump(), now + 30 * 86400)
        self.save("pair", hashlib.sha256(access.encode()).hexdigest(), {"access": access, "refresh": refresh}, now + 30 * 86400)
        self.save("pair", hashlib.sha256(refresh.encode()).hexdigest(), {"access": access, "refresh": refresh}, now + 30 * 86400)
        return OAuthToken(access_token=access, token_type="Bearer", expires_in=3600, refresh_token=refresh, scope=" ".join(scopes))

    async def exchange_authorization_code(self, client, authorization_code):
        if not self.take("code", authorization_code.code):
            raise TokenError("invalid_grant", "Code already consumed")
        return self.issue(client.client_id, authorization_code.scopes, authorization_code.resource)

    async def load_refresh_token(self, client, refresh_token):
        data = self.load("refresh", refresh_token)
        return RefreshToken.model_validate(data) if data else None

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        if not self.take("refresh", refresh_token.token):
            raise TokenError("invalid_grant", "Refresh token already consumed")
        await self.revoke_token(refresh_token)
        return self.issue(client.client_id, scopes, refresh_token.resource)

    async def load_access_token(self, token):
        data = self.load("access", token)
        return AccessToken.model_validate(data) if data else None

    async def revoke_token(self, token):
        pair = self.take("pair", hashlib.sha256(token.token.encode()).hexdigest())
        if pair:
            with self.db:
                for kind in ("access", "refresh"):
                    self.db.execute("DELETE FROM records WHERE kind=? AND key=?", (kind, pair[kind]))
                    self.db.execute("DELETE FROM records WHERE kind='pair' AND key=?", (hashlib.sha256(pair[kind].encode()).hexdigest(),))

    async def revoke_request(self, request):
        # SDK 2.2's revoke form requires client_secret even for public clients.
        try:
            client = await ClientAuthenticator(self).authenticate_request(request)
        except AuthenticationError:
            return JSONResponse({"error": "invalid_client"}, status_code=401)
        form = await request.form()
        value = str(form.get("token", ""))
        if not value:
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        token = await self.load_access_token(value) or await self.load_refresh_token(client, value)
        if token and token.client_id == client.client_id:
            await self.revoke_token(token)
        return PlainTextResponse("", headers={"Cache-Control": "no-store", "Pragma": "no-cache"})

    async def login(self, request):
        pending_id = request.query_params.get("request", "")
        pending = self.load("pending", pending_id)
        if not pending:
            return PlainTextResponse("Authorization request expired. Start connecting again.", status_code=400)
        params = AuthorizationParams.model_validate(pending["params"])
        headers = {"Cache-Control": "no-store", "Referrer-Policy": "same-origin", "X-Frame-Options": "DENY",
                   "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'"}
        if request.method == "POST":
            form = await request.form()
            csrf = str(form.get("csrf", ""))
            if (request.headers.get("origin") != self.base
                    or not secrets.compare_digest(csrf.encode(), pending["csrf"].encode())
                    or not secrets.compare_digest(request.cookies.get("siyuan_oauth_csrf", "").encode(), pending["csrf"].encode())):
                return PlainTextResponse("Invalid authorization form", status_code=403, headers=headers)
            if not secrets.compare_digest(str(form.get("password", "")).encode(), self.password.encode()):
                return PlainTextResponse("Incorrect password. Go back and try again.", status_code=403, headers=headers)
            if not self.take("pending", pending_id):
                return PlainTextResponse("Authorization request already used", status_code=400, headers=headers)
            code = secrets.token_urlsafe(32)
            grant = AuthorizationCode(
                code=code, client_id=pending["client_id"], scopes=params.scopes or ["siyuan"],
                expires_at=time.time() + 300, code_challenge=params.code_challenge,
                redirect_uri=params.redirect_uri,
                redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                resource=self.resource, subject="wenyuan",
            )
            self.save("code", code, grant.model_dump(mode="json"), grant.expires_at)
            response = RedirectResponse(construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state), status_code=303, headers=headers)
            response.delete_cookie("siyuan_oauth_csrf", path="/login")
            return response
        client = await self.get_client(pending["client_id"])
        name = html.escape(client.client_name or client.client_id)
        callback = html.escape(urlparse(str(params.redirect_uri)).netloc)
        body = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>连接思源笔记</title>
<style>body{{font:18px system-ui;max-width:560px;margin:10vh auto;padding:24px;line-height:1.6}}input,button{{font:inherit;padding:10px;box-sizing:border-box;width:100%;margin-top:12px}}small{{overflow-wrap:anywhere}}</style>
<h1>连接思源笔记</h1><p>客户端：<strong>{name}</strong><br>授权回调：<small>{callback}</small></p>
<p>允许此客户端读取、搜索和编辑你的思源笔记。请输入 MCP 连接密码以确认授权。</p>
<form method="post"><input type="hidden" name="csrf" value="{pending['csrf']}"><label>MCP 连接密码<input type="password" name="password" required autocomplete="current-password"></label><button>授权连接</button></form></html>'''
        response = HTMLResponse(body, headers=headers)
        response.set_cookie("siyuan_oauth_csrf", pending["csrf"], secure=True, httponly=True, samesite="lax", path="/login", max_age=600)
        return response
