import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlencode

from mcp.server.auth.provider import AuthorizationCode, TokenError
from mcp.shared.auth import OAuthClientInformationFull
from starlette.requests import Request

from oauth import PasswordOAuth


class OAuthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = str(Path(self.temp.name) / "oauth.sqlite3")
        self.provider = PasswordOAuth("https://notes.example", "test-password", self.database)
        self.client = OAuthClientInformationFull(
            client_id="client-a", redirect_uris=["https://client.example/callback"],
            token_endpoint_auth_method="none",
        )
        await self.provider.register_client(self.client)

    async def asyncTearDown(self):
        self.provider.db.close()
        self.temp.cleanup()

    def form_request(self, data):
        body = urlencode(data).encode()

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        return Request({
            "type": "http", "method": "POST", "path": "/revoke",
            "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
        }, receive)

    async def test_public_client_can_revoke_without_secret(self):
        tokens = self.provider.issue(self.client.client_id, ["siyuan"], self.provider.resource)
        request = self.form_request({"client_id": self.client.client_id, "token": tokens.refresh_token})
        response = await self.provider.revoke_request(request)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(await self.provider.load_access_token(tokens.access_token))
        self.assertIsNone(await self.provider.load_refresh_token(self.client, tokens.refresh_token))

    async def test_other_client_cannot_revoke_token(self):
        tokens = self.provider.issue(self.client.client_id, ["siyuan"], self.provider.resource)
        other = self.client.model_copy(update={"client_id": "client-b"})
        await self.provider.register_client(other)
        response = await self.provider.revoke_request(self.form_request({
            "client_id": other.client_id, "token": tokens.access_token,
        }))
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(await self.provider.load_access_token(tokens.access_token))

    async def test_refresh_rotates_pair_and_rejects_replay(self):
        tokens = self.provider.issue(self.client.client_id, ["siyuan"], self.provider.resource)
        refresh = await self.provider.load_refresh_token(self.client, tokens.refresh_token)
        rotated = await self.provider.exchange_refresh_token(self.client, refresh, ["siyuan"])
        self.assertIsNone(await self.provider.load_access_token(tokens.access_token))
        self.assertIsNotNone(await self.provider.load_access_token(rotated.access_token))
        with self.assertRaises(TokenError):
            await self.provider.exchange_refresh_token(self.client, refresh, ["siyuan"])

    async def test_code_can_only_be_used_once(self):
        import time
        code = AuthorizationCode(
            code="one-use-code", scopes=["siyuan"], expires_at=time.time() + 300,
            client_id=self.client.client_id, code_challenge="pkce-challenge",
            redirect_uri=self.client.redirect_uris[0], redirect_uri_provided_explicitly=True,
            resource=self.provider.resource,
        )
        self.provider.save("code", code.code, code.model_dump(mode="json"), code.expires_at)
        await self.provider.exchange_authorization_code(self.client, code)
        with self.assertRaises(TokenError):
            await self.provider.exchange_authorization_code(self.client, code)

    async def test_authorization_survives_reopening_database(self):
        tokens = self.provider.issue(self.client.client_id, ["siyuan"], self.provider.resource)
        reopened = PasswordOAuth(self.provider.base, "test-password", self.database)
        try:
            self.assertIsNotNone(await reopened.get_client(self.client.client_id))
            self.assertIsNotNone(await reopened.load_access_token(tokens.access_token))
        finally:
            reopened.db.close()


if __name__ == "__main__":
    unittest.main()
