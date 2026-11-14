import os
import unittest
from unittest.mock import Mock, patch

from starlette.testclient import TestClient

import homepage


class HomepageTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, SIYUAN_HOMEPAGE_TOKEN="test-homepage-token",
                         SIYUAN_HOMEPAGE_DOC_ID="20260922121644-b31zzdx")
        env.start()
        self.addCleanup(env.stop)

    def test_revision_avoids_resending_assets(self):
        markdown = "# Wenyuan Xu\nwenyuan.xu@cs.au.dk\n![photo](assets/photo.jpg)"
        with patch.object(homepage.upstream, "_post_to_siyuan_api", return_value={"content": markdown}) as api, \
                patch.object(homepage.upstream, "check_file"), \
                patch.object(homepage.upstream, "_get_siyuan_request_parts", return_value=("http://localhost", {})), \
                patch.object(homepage.requests, "post", return_value=Mock(content=b"\xffphoto", headers={"Content-Type": "image/jpeg"})) as asset:
            result = homepage.get_homepage()
            self.assertEqual(result["markdown"], markdown)
            self.assertEqual(result["assets"]["assets/photo.jpg"]["base64"], "/3Bob3Rv")
            self.assertEqual(homepage.get_homepage(result["revision"]), {"revision": result["revision"], "unchanged": True})
            self.assertEqual(asset.call_count, 1)
            api.assert_called_with("/api/export/exportMdContent", {"id": "20260922121644-b31zzdx"})

    def test_rejects_asset_traversal(self):
        with patch.object(homepage.upstream, "_post_to_siyuan_api", return_value={"content": "![x](assets/%2e%2e/conf.json)"}):
            with self.assertRaises(ValueError):
                homepage.get_homepage()

    def test_mcp_auth_and_single_tool_scope(self):
        app = homepage.build_homepage_app("https://siyuan-mcp.wenyuanxu.net")
        with TestClient(app, base_url="https://siyuan-mcp.wenyuanxu.net") as client:
            body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
            headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-03-26"}
            self.assertEqual(client.post("/mcp", json=body, headers=headers).status_code, 401)
            headers["Authorization"] = "Bearer test-homepage-token"
            response = client.post("/mcp", json=body, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual([tool["name"] for tool in response.json()["result"]["tools"]], ["get_homepage"])
            body.update(method="tools/call", params={"name": "execute_sql", "arguments": {"query": "SELECT * FROM blocks"}})
            result = client.post("/mcp", json=body, headers=headers).json()
            self.assertTrue(result.get("error") or result["result"].get("isError"))


if __name__ == "__main__":
    unittest.main()
