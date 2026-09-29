"""
DeepSeek-based summarizer for seven-country user research insights.
Uses the official DeepSeek OpenAI-compatible Chat Completions API.

Translates, summarises, filters and highlights news from
Russia, India, Indonesia, Nigeria, Kenya, Pakistan, Bangladesh.
"""

import json
import os
import re
import asyncio
from urllib.parse import urlsplit

import aiohttp

from collectors.base import NewsItem


def is_english(text: str) -> bool:
    """Check if text is primarily English (non-Chinese)."""
    if not text:
        return False
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    if chinese_chars >= 1:
        if len(text) > 30 and (chinese_chars / len(text)) < 0.05:
            return True
        return False
    return True


def _clean_json_response(text: str) -> str:
    """Clean DeepSeek JSON response (strip markdown code blocks)."""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


# Target countries for filtering
TARGET_COUNTRIES = [
    "Russia", "India", "Indonesia", "Nigeria", "Kenya", "Pakistan", "Bangladesh",
    "Russian", "Indian", "Indonesian", "Nigerian", "Kenyan", "Pakistani", "Bangladeshi",
    "Moscow", "Delhi", "Mumbai", "Jakarta", "Lagos", "Abuja", "Nairobi",
    "Karachi", "Islamabad", "Lahore", "Kolkata", "Chennai", "Bangalore",
    "Hyderabad", "Surabaya", "Bandung", "Kano", "Mombasa", "Peshawar",
    "Dhaka", "Chattogram", "Chittagong",
    "Africa", "African", "South Asia", "Southeast Asia",
]

VALID_COUNTRY_CODES = {
    "russia", "india", "indonesia", "nigeria", "kenya", "pakistan",
    "bangladesh", "multi"
}
VALID_CATEGORIES = {
    "macro_infra",
    "commerce_economy",
    "digital_ecosystem",
    "pop_culture",
    "mobile_market",
    "country_news",
}


class DeepSeekSummarizer:
    """Summarize with DeepSeek V4.1 Flash; credentials stay in the environment."""

    DEFAULT_MODEL = "deepseek-flash"
    DEFAULT_BASE_URL = "https://api.deepseek.com"

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 base_url: str | None = None):
        self.api_key = (api_key or os.environ.get("DEEPSEEK_API_KEY", "")).strip()
        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY is required")
        self.model_name = (model or os.environ.get("DEEPSEEK_MODEL") or self.DEFAULT_MODEL).strip()
        self.base_url = (base_url or os.environ.get("DEEPSEEK_BASE_URL") or self.DEFAULT_BASE_URL).strip().rstrip("/")
        parsed = urlsplit(self.base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("DEEPSEEK_BASE_URL must be an HTTPS API base URL without credentials or query")
        self.semaphore = asyncio.Semaphore(5)
        self.successful_calls = 0
        self.fatal_error = None
        print(f"   🧠 DeepSeek model: {self.model_name}")

    async def _call(self, prompt: str, *, json_mode: bool = False) -> str:
        """Return final content, retry transient failures, never log provider bodies."""
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "thinking": {"type": "disabled"},
            "temperature": 0.2,
            "max_tokens": 4096,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
            payload["messages"].insert(0, {"role": "system", "content": "Return only a valid JSON object matching the requested schema."})
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with self.semaphore:
            if self.fatal_error:
                raise RuntimeError(self.fatal_error)
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
                for attempt in range(3):
                    try:
                        async with session.post(
                            f"{self.base_url}/chat/completions", json=payload,
                            headers=headers, allow_redirects=False,
                        ) as response:
                            status = response.status
                            if status != 200:
                                if status == 429 or status >= 500:
                                    if attempt < 2:
                                        await asyncio.sleep(2 ** attempt)
                                        continue
                                error = f"DeepSeek HTTP {status}; check API key, balance, model and service status"
                                if status in {400, 401, 402, 403, 404, 422}:
                                    self.fatal_error = error
                                raise RuntimeError(error)
                            data = await response.json()
                        choices = data.get("choices") or []
                        if not choices or choices[0].get("finish_reason") == "length":
                            raise RuntimeError("DeepSeek returned missing or truncated content")
                        content = choices[0].get("message", {}).get("content")
                        if not isinstance(content, str) or not content.strip():
                            raise RuntimeError("DeepSeek returned empty content")
                        self.successful_calls += 1
                        return content.strip()
                    except (aiohttp.ClientError, asyncio.TimeoutError):
                        if attempt == 2:
                            raise RuntimeError("DeepSeek network error or timeout after 3 attempts") from None
                        await asyncio.sleep(2 ** attempt)
                    except (ValueError, KeyError, TypeError):
                        raise RuntimeError("DeepSeek returned an invalid response") from None
        raise RuntimeError("DeepSeek request failed")

    # ──────────────────────────────────────────────
    #  Translation
    # ──────────────────────────────────────────────

    async def translate_to_chinese(self, text: str) -> str:
        """Translate text to Simplified Chinese."""
        if not text or len(text) < 2:
            return text or ""

        prompt = f"""Translate the following text into Simplified Chinese (简体中文).

Original Text:
"{text}"

Task Instructions:
1. Translate into natural-sounding Simplified Chinese.
2. Keep proper nouns, brand names and technical terms in their original language (e.g., M-Pesa, Flutterwave, Jumia, TikTok, Google Play, UPI).
3. Keep country and city names in Chinese (e.g., 尼日利亚, 肯尼亚, 印度, 印尼, 巴基斯坦, 孟加拉). For Russia, ALWAYS write EE1 and NEVER write the Chinese label 俄罗斯.
4. Return ONLY the translated Chinese string — no quotes, no explanations.
"""
        try:
            result = await self._call(prompt)
            if (result.startswith('"') and result.endswith('"')) or \
               (result.startswith("'") and result.endswith("'")):
                result = result[1:-1].strip()
            return result
        except Exception as e:
            print(f"Translation error: {e}")
            return text

    # ──────────────────────────────────────────────
    #  Core: Classify + Summarize + Translate + Content filter
    # ──────────────────────────────────────────────

    async def summarize_and_translate(self, item: NewsItem) -> tuple[str, str, bool]:
        """Generate summary and translate. Returns (title, summary, is_translated)."""
        title = item.title
        summary = item.summary or ""
        is_translated = False

        raw_content = item.content if item.content and len(item.content) > len(item.summary or "") else (item.summary or "")

        # Content quality threshold: discard items shorter than 80 chars
        if len(raw_content.strip()) < 80:
            print(f"   🗑️ Content too short, discarding: {item.title[:40]}")
            return item.title, "IRRELEVANT", False

        if len(raw_content) > 10000:
            raw_content = raw_content[:10000] + "..."

        prompt = f"""You are a professional bilingual analyst specialising in user-research insights for emerging markets.
Your job is to evaluate news from seven target countries: Russia, India, Indonesia, Nigeria, Kenya, Pakistan, Bangladesh.

Title: {item.title}
Source: {item.source}
Content: {raw_content.strip()}

═══ TASK ═══

1. **CONTENT SAFETY CHECK** (mandatory first step):
   Return is_relevant=false immediately if the content contains:
   - Sexually explicit or pornographic material
   - Graphic violence or gore
   - Extreme political propaganda or hate speech
   - Terrorism promotion
   - Content that is purely about domestic politics with no relevance to market/consumer/tech insights

2. **RELEVANCE CHECK** — Is this news genuinely useful for "Mobile UX & Product Desktop Research" (移动端用研与产品洞察)?
   Your goal is to find insights that could inspire new smartphone OS features, hardware designs, app localizations, or digital marketing strategies.

   Return is_relevant=true ONLY IF the news significantly relates to ANY of these dimensions for the target countries (Pakistan, Russia, India, Indonesia, Nigeria, Kenya, Bangladesh):

   - 🏛️ Macro & Digital Survival: government tech/app regulations, data privacy laws, telecom pricing/5G, severe power grid instability, or crisis events that change how people use mobile devices.
   - 💰 Tech-Driven Commerce: inflation driving new digital behavior (e.g., micro-loans, BNPL), local e-commerce shifts, mobile money adoption, or digital tools for local merchants/gig workers.
   - 🚀 Digital Ecosystem & Tools: local startup funding, breakout apps/widgets, Google Play/App Store dynamics, super apps, or shifts in local digital productivity.
   - 🎭 Digital Lifestyle & Subcultures: Gen Z digital behavior, online gaming/fandom communities, shifts in social media *usage* (not just the content), or cultural events that influence digital aesthetics and localized campaigns.
   - 📱 Mobile Market & Hardware: smartphone launches, market share, brand dynamics (Transsion/Tecno/Infinix/itel, Samsung, Xiaomi, OPPO, vivo, realme), or hardware supply chain news.

   🚫 EXCLUSION RULES (Return is_relevant=false IMMEDIATELY if the news is about):
   1. Celebrity gossip, entertainment industry drama, or influencer feuds (e.g., comedians arguing, movie reviews).
   2. Routine local crime, standard political bickering, or generic sports match results.
   3. Broad macro-economics or societal news that has ZERO clear connection to digital consumption, tech habits, or mobile phone usage.

   Return is_relevant=false if it hits any exclusion rules OR if the relevance to mobile/digital UX is too weak.

3. **BILINGUAL TITLE REWRITE** — Write informative Chinese and English headlines:
   - The Chinese title MUST be in Simplified Chinese (简体中文)
   - Prefix both titles with the country flag emoji: 🇷🇺🇮🇳🇮🇩🇳🇬🇰🇪🇵🇰🇧🇩 (or 🌍 for multi-country)
   - Be SPECIFIC: WHO did WHAT in WHERE
   - Keep brand names / proper nouns in original language
   - Target: 20-40 characters
   - For Russia, write EE1 and never use the Chinese label 俄罗斯
   - The English title must be natural professional English, not a transliteration

4. **BILINGUAL SUMMARY** — Write matching Chinese and English summaries:
   - Chinese: 60-120 Chinese characters; English: 55-100 words
   - Both must cover what happened, key details, and **why it matters for user research / product insights**
   - Lead with the core fact — no vague openers
   - Professional, factual tone

5. **COUNTRY CLASSIFICATION** — Assign exactly one value:
   - russia, india, indonesia, nigeria, kenya, pakistan, bangladesh
   - Use multi only when the same event materially covers multiple target countries.

6. **CATEGORY CLASSIFICATION** — Reclassify by the article's actual insight value, not by the feed it came from. Assign exactly one value:
   - macro_infra: regulation, connectivity, network, electricity, crisis infrastructure
   - commerce_economy: payments, fintech adoption, e-commerce, purchasing power, consumer prices
   - digital_ecosystem: apps, startups, platform rules, digital services, productivity tools
   - pop_culture: digital behaviour, social-media usage, gaming/fandom, Gen Z subcultures
   - mobile_market: handsets, brands, shipments, pricing, retail channels, components
   - country_news: only for relevant cross-domain news that cannot fit the five categories above

7. **IMPORTANCE SCORE** — Integer from 1 to 5 for mobile UX/product research actionability.

Return ONLY a valid JSON object:
{{
    "is_relevant": true or false,
    "title_zh": "Chinese headline with country flag",
    "title_en": "English headline with country flag",
    "summary_zh": "Chinese summary",
    "summary_en": "English summary",
    "country": "india",
    "category": "commerce_economy",
    "importance_score": 4
}}
"""

        try:
            text_response = _clean_json_response(await self._call(prompt, json_mode=True))

            try:
                data = json.loads(text_response)

                if not data.get("is_relevant", True):
                    return item.title, "IRRELEVANT", False

                country = str(data.get("country", "")).strip().lower()
                if country in VALID_COUNTRY_CODES:
                    item.country = country

                category = str(data.get("category", "")).strip().lower()
                if category in VALID_CATEGORIES:
                    item.category = category

                try:
                    importance = float(data.get("importance_score", 0.0))
                    item.relevance_score = min(5.0, max(0.0, importance))
                except (TypeError, ValueError):
                    item.relevance_score = 0.0

                json_title = (
                    data.get("title_zh", "") or data.get("title", "")
                ).strip()
                title = json_title if json_title else item.title

                summary = (
                    data.get("summary_zh", "") or data.get("summary", "")
                ).strip()
                item.title_en = data.get("title_en", "").strip() or item.title
                item.summary_en = (
                    data.get("summary_en", "").strip()
                    or item.summary
                    or ""
                )
                is_translated = is_english(item.title)

                title = re.sub(r'^AI[:：]\s*(YES|NO|Related).*?[:：]\s*', '', title, flags=re.IGNORECASE).strip()

                if not summary or len(summary.strip()) < 5:
                    if title:
                        summary = f"{title}（点击查看详情）"
                    else:
                        summary = "暂无详细摘要，请点击标题查看原文。"

                # Force translate if still English
                if is_english(summary) and len(summary) > 10:
                    try:
                        summary = await self.translate_to_chinese(summary)
                    except Exception:
                        pass

                if is_english(title) and len(title) >= 3:
                    try:
                        translated_title = await self.translate_to_chinese(title)
                        if translated_title and not is_english(translated_title):
                            title = translated_title
                    except Exception as e:
                        print(f"   Title translation failed: {e}")

                return title, summary, is_translated

            except json.JSONDecodeError:
                print(f"JSON Parse Error for '{item.title}': {text_response[:50]}...")
                return item.title, "Summary generation failed (JSON Error)", False

        except Exception as e:
            print(f"Translate & summarize error for '{item.title[:20]}...': {e}")
            if is_english(item.title):
                try:
                    translated = await self.translate_to_chinese(item.title)
                    if translated and not is_english(translated):
                        title = translated
                        is_translated = True
                except Exception:
                    pass
            if item.summary and is_english(item.summary):
                try:
                    summary = await self.translate_to_chinese(item.summary)
                except Exception:
                    summary = item.summary
            else:
                summary = item.summary or ""

        item.title_en = item.title_en or item.title
        item.summary_en = item.summary_en or item.summary or ""

        if summary and len(summary) > 300:
            summary = summary[:297] + "..."

        return title, summary, is_translated

    # ──────────────────────────────────────────────
    #  Daily highlights
    # ──────────────────────────────────────────────

    async def generate_daily_highlights(
        self,
        items_by_category: dict[str, list[NewsItem]],
        category_names: dict[str, str]
    ) -> str:
        """Generate daily highlights with HTML formatting."""

        content_parts = []
        for category, items in items_by_category.items():
            cat_name = category_names.get(category, category)
            content_parts.append(f"\n## {cat_name}")
            for item in items[:5]:
                content_parts.append(f"- {item.title} ({item.source})")

        all_content = "\n".join(content_parts)

        prompt = f"""You are a senior user-research analyst covering seven emerging markets: Russia, India, Indonesia, Nigeria, Kenya, Pakistan, Bangladesh.

Based on the following news list, select the top 3 most important insights for product teams and user researchers today.

News List:
{all_content}

Task Instructions:
1. Select exactly 3 items that are most actionable for product/UX teams building for these markets.
2. Prioritise: infrastructure changes that affect device usage, consumer behaviour shifts, breakout apps or services, and cultural moments that reveal user needs.
3. When quality allows, cover at least 2 different target countries; do not select three near-duplicate India/Africa/global stories.
4. Write each highlight as a complete sentence in Simplified Chinese (简体中文).
5. Each highlight should explain WHY it matters for user research, not just WHAT happened.
6. For Russia, write EE1 and never use the Chinese label 俄罗斯.

Return ONLY a valid JSON object:
{{
    "highlights": [
        "First insight in Chinese — what happened and why it matters.",
        "Second insight in Chinese.",
        "Third insight in Chinese."
    ]
}}
"""

        try:
            text_response = _clean_json_response(await self._call(prompt, json_mode=True))

            try:
                data = json.loads(text_response)
                highlights_list = data.get("highlights", [])

                html_parts = []
                for i, highlight in enumerate(highlights_list, 1):
                    clean_highlight = re.sub(r'^(AI[:：]\s*(YES|NO|Related)|Title:|Summary:).*?[:：]\s*', '', highlight, flags=re.IGNORECASE).strip()
                    if clean_highlight:
                        html_parts.append(
                            f'<div class="highlight-item">'
                            f'<span class="highlight-number">{i}</span>'
                            f'<span class="highlight-text">{clean_highlight}</span>'
                            f'</div>'
                        )

                if html_parts:
                    return '\n'.join(html_parts)

            except json.JSONDecodeError:
                print(f"JSON Parse Error for highlights: {text_response[:50]}...")
                return self._format_highlights_html(text_response)

            return "今日七国洞察收集完成，请查看下方详情。"

        except Exception as e:
            print(f"Highlights error: {e}")
            return "今日七国洞察收集完成，请查看下方详情。"


    def _format_highlights_html(self, text: str) -> str:
        """Convert highlight text to HTML format."""
        html_parts = []

        pattern_num = r'(\d+)[.、．]\s*'
        parts_num = re.split(pattern_num, text)

        if len(parts_num) > 1:
            i = 1
            while i < len(parts_num):
                if parts_num[i].isdigit():
                    number = parts_num[i]
                    content = parts_num[i + 1].strip() if i + 1 < len(parts_num) else ""
                    if content:
                        html_parts.append(
                            f'<div class="highlight-item">'
                            f'<span class="highlight-number">{number}</span>'
                            f'<span class="highlight-text">{content}</span>'
                            f'</div>'
                        )
                    i += 2
                else:
                    i += 1
        else:
            lines = text.split('\n')
            counter = 1
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                clean_line = re.sub(r'^[-*•]\s*', '', line)
                if clean_line:
                    html_parts.append(
                        f'<div class="highlight-item">'
                        f'<span class="highlight-number">{counter}</span>'
                        f'<span class="highlight-text">{clean_line}</span>'
                        f'</div>'
                    )
                    counter += 1

        if html_parts:
            return '\n'.join(html_parts)
        else:
            return f'<div class="highlight-item"><span class="highlight-text">{text}</span></div>'

    # ──────────────────────────────────────────────
    #  Batch processing
    # ──────────────────────────────────────────────

    async def process_and_filter_items(
        self,
        items: list[NewsItem],
        max_items: int = 30,
    ) -> tuple[list[NewsItem], int]:
        """Process items with translation, filter irrelevant content.
        Returns (valid_items, translated_count)."""
        print(f"🌐 Translating {len(items)} items...")

        tasks = []
        for item in items:
            tasks.append(self.summarize_and_translate(item))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        valid_items = []
        translated_count = 0

        for i, result in enumerate(results):
            item = items[i]

            if isinstance(result, Exception):
                print(f"   Translation error for '{item.title[:30]}...': {result}")
                valid_items.append(item)
                continue

            title, summary, is_translated = result

            if summary and "IRRELEVANT" in summary:
                print(f"   🚫 Skipping irrelevant item: {item.title}")
                continue

            if not title or not title.strip() or not summary or len(summary.strip()) < 5:
                print(f"   🚫 Skipping item with missing title/summary: {item.title[:30]}")
                continue

            item.title = title
            item.summary = summary
            item.is_translated = is_translated
            if is_translated:
                translated_count += 1

            valid_items.append(item)

        print(f"   Translated {translated_count} items (Filtered {len(items) - len(valid_items)} irrelevant)\n")
        return valid_items, translated_count

    # ──────────────────────────────────────────────
    #  Semantic deduplication
    # ──────────────────────────────────────────────

    async def semantic_deduplicate(
        self,
        categories: dict[str, list['NewsItem']],
    ) -> dict[str, list['NewsItem']]:
        """Use DeepSeek to identify cross-source duplicate stories."""

        all_items: list[tuple[str, 'NewsItem']] = []
        for cat, items in categories.items():
            for item in items:
                all_items.append((cat, item))

        if len(all_items) <= 1:
            return categories

        titles_text = "\n".join(
            f"{i}: {item.title} [{item.source}]"
            for i, (_, item) in enumerate(all_items)
        )

        prompt = f"""You are a professional news editor. Group the following headlines into identical topics/events.

News Headlines:
{titles_text}

Task Instructions:
1. Identify groups of headlines reporting on the EXACT SAME specific event.
2. Only group if they are clearly about the same release, event, or announcement.
3. If no identical events exist, return an empty array.

Return ONLY a valid JSON object:
{{
    "groups": [[0, 3, 7], [2, 5]]
}}
Each sub-array contains index numbers of news items about the same event.
"""

        try:
            text_response = _clean_json_response(await self._call(prompt, json_mode=True))

            data = json.loads(text_response)
            groups = data.get("groups", [])

            if not groups:
                return categories

            indices_to_remove: set[int] = set()
            for group in groups:
                if len(group) < 2:
                    continue
                best_idx = max(
                    group,
                    key=lambda idx: len((all_items[idx][1].content or "") + (all_items[idx][1].summary or ""))
                    if 0 <= idx < len(all_items) else 0,
                )
                for idx in group:
                    if idx != best_idx and 0 <= idx < len(all_items):
                        removed = all_items[idx][1]
                        kept = all_items[best_idx][1]
                        print(f"   🔗 Dedup: removed「{removed.title[:30]}」({removed.source}), kept「{kept.title[:30]}」({kept.source})")
                        indices_to_remove.add(idx)

            new_categories: dict[str, list['NewsItem']] = {cat: [] for cat in categories}
            for i, (cat, item) in enumerate(all_items):
                if i not in indices_to_remove:
                    new_categories[cat].append(item)

            new_categories = {cat: items for cat, items in new_categories.items() if items}

            removed_count = len(indices_to_remove)
            if removed_count:
                print(f"   ✅ Semantic dedup done: removed {removed_count} duplicates")

            return new_categories

        except Exception as e:
            print(f"   ⚠️ Semantic dedup failed (keeping all): {e}")
            return categories

    async def batch_summarize(
        self,
        items: list[NewsItem],
        max_items: int = 20
    ) -> list[NewsItem]:
        """Batch summarize multiple items."""
        valid, _ = await self.process_and_filter_items(items, max_items)
        return valid
