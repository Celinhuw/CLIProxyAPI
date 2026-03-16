"""PJe monitor tools: direct court system scraping as fallback.

Uses Selenium headless browser to query PJe (Processo Judicial Eletrônico)
when INTIMA.AI is unavailable or for courts not covered by the API.
Adapted from odantasvictor/movimentacoes_processuais pattern.
"""

import asyncio
import json
import logging
import os
import re
import tempfile

from agent import tool

LOGGER = logging.getLogger("shadow_claw_gateway.tools.pje_monitor")

_PJE_TIMEOUT = 60  # seconds per query
_PJE_BASE_URLS = {
    "trt": "https://pje.trt{region}.jus.br",
    "tst": "https://pje.tst.jus.br",
    "tjsp": "https://pje.tjsp.jus.br",
}

# Regex for Brazilian case numbers: NNNNNNN-NN.NNNN.N.NN.NNNN
_RE_PROCESSO = re.compile(r"^\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}$")


def _validate_processo(numero: str) -> str | None:
    numero = numero.strip()
    if _RE_PROCESSO.match(numero):
        return numero
    return None


def _validate_oab(oab: str) -> str | None:
    """Validate OAB number format: NNNNNN/UF or UF/NNNNNN."""
    oab = oab.strip().upper()
    if re.match(r"^\d{3,6}/[A-Z]{2}$", oab):
        return oab
    if re.match(r"^[A-Z]{2}/\d{3,6}$", oab):
        return oab
    return None


async def _run_selenium_query(url: str, processo: str) -> dict:
    """Run a PJe consultation via Selenium headless."""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
    except ImportError:
        return {"ok": False, "error": "selenium not installed. Run: pip install selenium"}

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")

    driver = None
    try:
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(_PJE_TIMEOUT)

        # Navigate to PJe public consultation
        consultation_url = f"{url}/consultaprocessual/detalhe-processo/{processo}"
        driver.get(consultation_url)

        # Wait for page load
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # Extract page text
        body = driver.find_element(By.TAG_NAME, "body")
        text = body.text

        if not text.strip() or "não encontrado" in text.lower():
            return {"ok": False, "error": f"Case not found: {processo}"}

        return {"ok": True, "content": text[:3000]}

    except Exception as e:
        return {"ok": False, "error": f"Selenium PJe query failed: {e}"}
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


@tool(
    "check_pje",
    "Query PJe (Processo Judicial Eletrônico) directly for case information. "
    "Use as fallback when INTIMA.AI doesn't cover the tribunal.",
    {
        "type": "object",
        "properties": {
            "processo": {
                "type": "string",
                "description": "Case number in CNJ format (e.g., '0001234-56.2026.5.01.0001')",
            },
            "tribunal": {
                "type": "string",
                "description": "Tribunal code: 'trt1'..'trt24', 'tst', 'tjsp'",
            },
        },
        "required": ["processo"],
    },
)
async def check_pje(processo: str, tribunal: str = "trt1") -> str:
    clean = _validate_processo(processo)
    if not clean:
        return "Invalid case number. Use CNJ format: 0001234-56.2026.5.01.0001"

    tribunal = tribunal.lower().strip()

    # Determine base URL
    if tribunal.startswith("trt"):
        region = tribunal.replace("trt", "")
        base_url = _PJE_BASE_URLS["trt"].format(region=region)
    elif tribunal in _PJE_BASE_URLS:
        base_url = _PJE_BASE_URLS[tribunal]
    else:
        return f"Unknown tribunal: {tribunal}. Supported: trt1-trt24, tst, tjsp"

    result = await _run_selenium_query(base_url, clean)

    if not result["ok"]:
        return result["error"]

    return f"PJe result for {clean} ({tribunal}):\n\n{result['content']}"


@tool(
    "list_my_cases",
    "Search PJe for all cases linked to an OAB number. "
    "Returns a list of active cases for the lawyer.",
    {
        "type": "object",
        "properties": {
            "oab_number": {
                "type": "string",
                "description": "OAB number (e.g., '123456/SP' or 'SP/123456')",
            },
        },
        "required": ["oab_number"],
    },
)
async def list_my_cases(oab_number: str) -> str:
    clean = _validate_oab(oab_number)
    if not clean:
        return "Invalid OAB number. Use format: 123456/SP or SP/123456"

    # Redirect to INTIMA.AI which supports OAB-based search
    try:
        from tools.legal import _intima_request
        data = await _intima_request("processos/consulta", {"oab": clean})
        cases = data.get("data", [])
        if not cases:
            return f"No active cases found for OAB {clean}."

        if isinstance(cases, dict):
            cases = [cases]

        lines = [f"📋 **Processos vinculados à OAB {clean}:**\n"]
        for case in cases[:20]:
            numero = case.get("numero_processo", case.get("processo", "?"))
            tribunal = case.get("tribunal", case.get("orgao", ""))
            status = case.get("status", case.get("situacao", ""))
            lines.append(f"  - {numero} ({tribunal}) — {status}")

        if len(cases) > 20:
            lines.append(f"\n... e mais {len(cases) - 20} processos.")

        return "\n".join(lines)
    except ValueError as e:
        return str(e)
    except Exception as e:
        return f"Failed to query cases for OAB {clean}: {e}"
