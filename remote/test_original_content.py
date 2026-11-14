"""Verify content fidelity across the tools previously rewriting source data."""
import base64
import unittest
from unittest.mock import Mock, patch

import siyuan_mcp_server as api


class OriginalContentTests(unittest.TestCase):
    text = 'wenyuan.xu@cs.au.dk https://scheduler.zoom.us/wenyuan-xu/meeting assets/IMG-20260515100457094-20260922121644-8lcrxij.jpg ghp_abcdefghijklmnopqrstuvwxyz0123456789'

    def test_block_and_batch_keep_kramdown_and_attributes(self):
        result = {"id": "20260922121644-b31zzdx", "kramdown": self.text + '\n{:title="' + self.text + '"}'}
        with patch.object(api, "_post_to_siyuan_api", return_value=result):
            self.assertEqual(api.get_block_content(result["id"]), result)
            self.assertEqual(api.get_blocks_content([result["id"]]), [result])

    def test_sql_and_search_keep_all_fields(self):
        result = [{"id": "20260922121644-b31zzdx", "content": self.text, "markdown": self.text}]
        with patch.object(api, "_post_to_siyuan_api", return_value=result):
            self.assertEqual(api.execute_sql("SELECT * FROM blocks LIMIT 1"), result)
            self.assertEqual(api.search_blocks("Wenyuan"), result)
        self.assertEqual(result[0]["content"], self.text)

    @patch.object(api, "_get_siyuan_request_parts", return_value=("http://localhost", {}))
    @patch.object(api.requests, "post")
    @patch.object(api, "check_file")
    def test_text_and_binary_files_keep_original_bytes(self, check_file, post, request_parts):
        response = Mock(content=self.text.encode())
        post.return_value = response
        self.assertEqual(api.get_file("/data/example.txt"), self.text)
        self.assertEqual(base64.b64decode(api.get_file_base64("/data/example.txt")), response.content)
        response.content = b"\xff\x00\x80image"
        self.assertEqual(base64.b64decode(api.get_file_base64("/data/photo.jpg")), response.content)


if __name__ == "__main__":
    unittest.main()
