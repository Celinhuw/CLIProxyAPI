"""Tests for tools/n8n_bridge.py — n8n workflow integration."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from tools.n8n_bridge import n8n_list_workflows, n8n_trigger_workflow, n8n_status


class TestN8nListWorkflows(unittest.IsolatedAsyncioTestCase):

    @patch("tools.n8n_bridge._n8n_request")
    async def test_list_workflows(self, mock_req):
        mock_req.return_value = {
            "data": [
                {"id": "1", "name": "Meta Ads Daily", "active": True},
                {"id": "2", "name": "PJe Monitor", "active": False},
            ]
        }
        result = await n8n_list_workflows()
        self.assertIn("Meta Ads Daily", result)
        self.assertIn("🟢", result)
        self.assertIn("⚪", result)

    @patch("tools.n8n_bridge._n8n_request")
    async def test_empty_workflows(self, mock_req):
        mock_req.return_value = {"data": []}
        result = await n8n_list_workflows()
        self.assertIn("No n8n workflows", result)

    @patch("tools.n8n_bridge._n8n_request")
    async def test_connection_error(self, mock_req):
        mock_req.return_value = {"error": "n8n not running"}
        result = await n8n_list_workflows()
        self.assertIn("not running", result)


class TestN8nTrigger(unittest.IsolatedAsyncioTestCase):

    async def test_invalid_workflow_id(self):
        result = await n8n_trigger_workflow("")
        self.assertIn("Invalid workflow ID", result)

    async def test_invalid_json_data(self):
        result = await n8n_trigger_workflow("1", data="not json")
        self.assertIn("Invalid JSON", result)

    @patch("tools.n8n_bridge.httpx.AsyncClient")
    @patch("tools.n8n_bridge._get_n8n_config", return_value=("http://localhost:5678", "key"))
    async def test_successful_trigger(self, mock_config, mock_client_cls):
        mock_resp = MagicMock(status_code=200)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        result = await n8n_trigger_workflow("1")
        self.assertIn("triggered", result)


class TestN8nStatus(unittest.IsolatedAsyncioTestCase):

    @patch("tools.n8n_bridge._n8n_request", new_callable=AsyncMock)
    @patch("tools.n8n_bridge.httpx.AsyncClient")
    async def test_healthy(self, mock_client_cls, mock_req):
        # Mock the async context manager
        mock_resp = MagicMock(status_code=200)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        mock_req.return_value = {"data": []}
        result = await n8n_status()
        self.assertIn("Running", result)

    @patch("tools.n8n_bridge.httpx.AsyncClient")
    async def test_not_running(self, mock_client_cls):
        import httpx as _httpx
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=_httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client
        result = await n8n_status()
        self.assertIn("not running", result)


if __name__ == "__main__":
    unittest.main()
