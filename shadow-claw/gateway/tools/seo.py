"""SEO tools: GEO-SEO analysis for law firm visibility.

Inspired by zubair-trabzada/geo-seo-claude (#106). Analyzes how
citeable the law firm is by AI search engines (ChatGPT, Perplexity,
Gemini) and provides optimization recommendations.

Different from traditional SEO: GEO-SEO focuses on making content
that AI systems will cite when users ask about legal services.
"""

import logging
import re

from agent import tool
from tools.browser import browse_url, browse_search

LOGGER = logging.getLogger("shadow_claw_gateway.tools.seo")


@tool(
    "geo_seo_audit",
    "Audit a website for GEO-SEO (Generative Engine Optimization). "
    "Checks if the site is structured for AI citation by ChatGPT, "
    "Perplexity, and Gemini. Optimized for Brazilian law firms.",
    {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Website URL to audit",
            },
            "keywords": {
                "type": "string",
                "description": "Target keywords (comma-separated, e.g., 'advogado trabalhista, São Paulo')",
            },
        },
        "required": ["url"],
    },
)
async def geo_seo_audit(url: str, keywords: str = "") -> str:
    # Fetch the page
    page_content = await browse_url(url)
    if "URL blocked" in page_content or "Error fetching" in page_content:
        return page_content

    checks = []
    score = 0
    total_checks = 8

    # 1. Schema.org structured data
    has_schema = "schema.org" in page_content.lower() or "application/ld+json" in page_content.lower()
    if has_schema:
        checks.append("✅ Schema.org structured data detected")
        score += 1
    else:
        checks.append("❌ No Schema.org — add LocalBusiness + LegalService markup")

    # 2. FAQ sections (AI loves extracting these)
    has_faq = any(kw in page_content.lower() for kw in ["faq", "perguntas frequentes", "dúvidas"])
    if has_faq:
        checks.append("✅ FAQ section found")
        score += 1
    else:
        checks.append("❌ No FAQ — add 'Perguntas Frequentes' section with Q&A pairs")

    # 3. Contact information visibility
    has_contact = any(kw in page_content.lower() for kw in ["tel:", "telefone", "whatsapp", "oab"])
    if has_contact:
        checks.append("✅ Contact info visible")
        score += 1
    else:
        checks.append("❌ Contact info missing — add phone, WhatsApp, OAB number")

    # 4. Location signals
    has_location = any(kw in page_content.lower() for kw in ["endereço", "localização", "cep", "rua", "avenida"])
    if has_location:
        checks.append("✅ Location signals present")
        score += 1
    else:
        checks.append("❌ No location signals — add full address for local SEO")

    # 5. Expert credentials (OAB, specializations)
    has_credentials = any(kw in page_content.lower() for kw in ["oab", "especialista", "pós-graduação", "mestre", "doutor"])
    if has_credentials:
        checks.append("✅ Expert credentials displayed")
        score += 1
    else:
        checks.append("❌ No credentials — display OAB number, specializations, education")

    # 6. Content depth (AI prefers detailed pages)
    word_count = len(page_content.split())
    if word_count > 500:
        checks.append(f"✅ Content depth OK ({word_count} words)")
        score += 1
    else:
        checks.append(f"❌ Thin content ({word_count} words) — aim for 800+ words per page")

    # 7. HTTPS
    if url.startswith("https://"):
        checks.append("✅ HTTPS enabled")
        score += 1
    else:
        checks.append("❌ No HTTPS — critical for trust signals")

    # 8. Mobile-friendly meta
    has_viewport = "viewport" in page_content.lower()
    if has_viewport:
        checks.append("✅ Mobile viewport meta tag")
        score += 1
    else:
        checks.append("❌ No viewport meta — add mobile-responsive meta tag")

    # Keyword citation check
    keyword_section = ""
    if keywords:
        kw_list = [k.strip() for k in keywords.split(",")]
        keyword_section = "\n\n🔍 **Keyword Analysis:**"
        for kw in kw_list[:5]:
            kw_lower = kw.lower()
            count = page_content.lower().count(kw_lower)
            if count > 0:
                keyword_section += f"\n  ✅ '{kw}' — found {count}x"
            else:
                keyword_section += f"\n  ❌ '{kw}' — NOT found on page"

    grade = "A" if score >= 7 else "B" if score >= 5 else "C" if score >= 3 else "D"

    return (
        f"🔎 **GEO-SEO Audit** — {url}\n"
        f"Score: {score}/{total_checks} (Grade: {grade})\n\n"
        + "\n".join(checks)
        + keyword_section
        + "\n\n💡 GEO-SEO foca em tornar seu site citável por AI (ChatGPT, Perplexity, Gemini)."
    )


@tool(
    "seo_competitor_check",
    "Check how competitors rank for target keywords in search results.",
    {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (e.g., 'advogado trabalhista São Paulo')",
            },
        },
        "required": ["query"],
    },
)
async def seo_competitor_check(query: str) -> str:
    results = await browse_search(query)
    return f"🏆 **Competitor Analysis** for '{query}':\n\n{results}"
