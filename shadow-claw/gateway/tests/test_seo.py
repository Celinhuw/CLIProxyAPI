"""Tests for tools/seo.py — GEO-SEO audit."""

import unittest
from unittest.mock import AsyncMock, patch

from tools.seo import geo_seo_audit, seo_competitor_check


class TestGeoSeoAudit(unittest.IsolatedAsyncioTestCase):

    @patch("tools.seo.browse_url")
    async def test_audit_perfect_site(self, mock_browse):
        mock_browse.return_value = (
            "Page content from https://example.com:\n\n"
            "schema.org application/ld+json viewport "
            "Perguntas Frequentes FAQ telefone WhatsApp OAB 12345 "
            "endereço Rua das Flores 123 CEP 01234-567 "
            "especialista pós-graduação " + "word " * 500
        )
        result = await geo_seo_audit("https://example.com", keywords="advogado,trabalhista")
        self.assertIn("Grade: A", result)
        self.assertIn("✅ Schema.org", result)

    @patch("tools.seo.browse_url")
    async def test_audit_poor_site(self, mock_browse):
        mock_browse.return_value = "Page content from http://bad.com:\n\nHello world"
        result = await geo_seo_audit("http://bad.com")
        self.assertIn("Grade: D", result)
        self.assertIn("❌", result)

    @patch("tools.seo.browse_url")
    async def test_blocked_url(self, mock_browse):
        mock_browse.return_value = "URL blocked: cannot access internal/private addresses."
        result = await geo_seo_audit("http://localhost")
        self.assertIn("URL blocked", result)

    @patch("tools.seo.browse_url")
    async def test_keyword_analysis(self, mock_browse):
        mock_browse.return_value = "Page content:\n\nadvogado trabalhista em São Paulo especialista"
        result = await geo_seo_audit("https://ex.com", keywords="advogado,inexistente")
        self.assertIn("'advogado' — found", result)
        self.assertIn("'inexistente' — NOT found", result)


class TestCompetitorCheck(unittest.IsolatedAsyncioTestCase):

    @patch("tools.seo.browse_search")
    async def test_returns_results(self, mock_search):
        mock_search.return_value = "Search results for 'advogado sp':\n\n- Result 1\n- Result 2"
        result = await seo_competitor_check("advogado sp")
        self.assertIn("Competitor Analysis", result)
        self.assertIn("Result 1", result)


if __name__ == "__main__":
    unittest.main()
