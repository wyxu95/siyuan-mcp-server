import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from siyuan_mcp_server.access import (
    check_file, filter_response, notebook_policy, prepare_request, scope_sql, web_client,
)
from server import ClientAccessMiddleware


class NotebookAccessTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute("CREATE TABLE blocks(id,box,content)")
        self.db.executemany("INSERT INTO blocks VALUES(?,?,?)", [
            ("public", "home", "homepage"), ("private", "alibaba", "company"), ("diary-block", "diary", "diary"),
        ])
        self.db.execute("CREATE TABLE assets(box,path)")
        self.db.executemany("INSERT INTO assets VALUES(?,?)", [("alibaba", "assets/company.jpg"), ("home", "assets/photo.jpg")])
        self.notebooks = [{"id": "home", "name": "Wenyuan Xu"}, {"id": "alibaba", "name": "Alibaba"}, {"id": "diary", "name": "Diary"}]
        self.addCleanup(self.db.close)

    def raw(self, endpoint, data=None):
        if endpoint == "/api/notebook/lsNotebooks":
            return {"notebooks": self.notebooks}
        return [dict(row) for row in self.db.execute(data["stmt"])]

    def test_local_and_web_notebook_policy(self):
        self.assertEqual(notebook_policy(self.raw)[1], {"alibaba"})
        token = web_client.set(True)
        try:
            self.assertEqual(notebook_policy(self.raw)[1], {"alibaba", "diary"})
            result = filter_response("/api/notebook/lsNotebooks", {"notebooks": self.notebooks}, {"alibaba", "diary"}, self.raw)
            self.assertEqual([row["id"] for row in result["notebooks"]], ["home"])
        finally:
            web_client.reset(token)

    def test_sql_scopes_before_projection_and_aggregation(self):
        for query in [
            "SELECT content AS arbitrary FROM blocks",
            "WITH x AS (SELECT content FROM blocks) SELECT * FROM x",
            "SELECT content FROM blocks UNION SELECT content FROM blocks",
            "SELECT a.content FROM blocks a JOIN blocks b ON a.id=b.id",
            "SELECT (SELECT content FROM blocks WHERE id='private') FROM blocks LIMIT 1",
        ]:
            result = self.raw("/api/query/sql", {"stmt": scope_sql(query, {"alibaba", "diary"})})
            values = [value for row in result for value in row.values()]
            self.assertNotIn("company", values)
            self.assertNotIn("diary", values)
        self.assertEqual(self.db.execute(scope_sql("SELECT count(*) FROM blocks", {"alibaba"})).fetchone()[0], 2)

    def test_sql_rejects_unknown_tables_and_cte_scope_bypass(self):
        for query in [
            "SELECT * FROM sqlite_master",
            "SELECT * FROM blocks_fts WHERE EXISTS (WITH blocks_fts AS (SELECT 1) SELECT * FROM blocks_fts)",
            "SELECT * FROM main.blocks", "SELECT readfile('/data/storage')", "SELECT 1; SELECT 2",
            "SELECT * FROM pragma_table_info('blocks')",
        ]:
            with self.assertRaises(PermissionError, msg=query):
                scope_sql(query, {"alibaba"})

    def test_block_reads_and_writes_are_checked(self):
        for endpoint in ["/api/block/getBlockKramdown", "/api/block/updateBlock", "/api/export/exportMdContent"]:
            with self.assertRaises(PermissionError):
                prepare_request(endpoint, {"id": "private"}, self.raw)
        with self.assertRaises(PermissionError):
            prepare_request("/api/block/moveBlock", {"id": "public", "parentID": "private"}, self.raw)
        prepare_request("/api/block/getBlockKramdown", {"id": "diary-block"}, self.raw)
        token = web_client.set(True)
        try:
            with self.assertRaises(PermissionError):
                prepare_request("/api/block/getBlockKramdown", {"id": "diary-block"}, self.raw)
        finally:
            web_client.reset(token)

    def test_files_and_assets_follow_notebook_access(self):
        check_file("/data/home/public.sy", self.raw)
        check_file("/data/assets/photo.jpg", self.raw)
        for path in ["/data/alibaba/private.sy", "/data/assets/company.jpg", "/data/conf/conf.json", "/data/storage.db", "/history/snapshot/blocks.msgpack", "/data/home/../alibaba/private.sy"]:
            with self.assertRaises(PermissionError, msg=path):
                check_file(path, self.raw)


class ClientClassificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cli_allowlist_and_web_default(self):
        provider = SimpleNamespace(load_access_token=AsyncMock(return_value=SimpleNamespace(client_id="codex")))
        middleware = ClientAccessMiddleware(None, provider, {"codex", "claude-cli"})
        request = SimpleNamespace(headers={"Authorization": "Bearer token"})

        async def check(request):
            return web_client.get()

        self.assertFalse(await middleware.dispatch(request, check))
        provider.load_access_token.return_value.client_id = "claude-cli"
        self.assertFalse(await middleware.dispatch(request, check))
        provider.load_access_token.return_value.client_id = "chatgpt"
        self.assertTrue(await middleware.dispatch(request, check))
        self.assertFalse(web_client.get())


if __name__ == "__main__":
    unittest.main()
