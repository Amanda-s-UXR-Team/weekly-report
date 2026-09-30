import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from collectors.base import NewsItem
from email_sender import EmailSender
from processors.deduper import (
    COUNTRY_PRIORITY,
    TARGET_COUNTRIES,
    balanced_limit,
    filter_by_date,
    finalize_categories,
    infer_country,
    limit_total_items,
)
from reporting import build_source_appendix


ROOT = Path(__file__).resolve().parents[1]


def make_item(
    title: str,
    country: str,
    *,
    category: str = "competitor_product",
    score: float = 8.0,
    source_priority: float = 2.0,
) -> NewsItem:
    return NewsItem(
        title=title,
        url=f"https://example.com/{country}/{title}",
        source="Test",
        category=category,
        country=country,
        editorial_score=score,
        relevance_score=score,
        source_priority=source_priority,
        published=datetime.now(timezone.utc),
    )


class MarketScopeTests(unittest.TestCase):
    def test_target_markets_and_priorities(self):
        self.assertEqual(
            TARGET_COUNTRIES,
            ("kenya", "tanzania", "nigeria", "uganda", "ghana", "pakistan", "bangladesh"),
        )
        self.assertEqual(
            {country for country, priority in COUNTRY_PRIORITY.items() if priority == "A"},
            {"kenya", "tanzania", "nigeria"},
        )
        self.assertEqual(
            {country for country, priority in COUNTRY_PRIORITY.items() if priority == "B+"},
            {"uganda", "ghana", "pakistan", "bangladesh"},
        )

    def test_country_metadata_is_attached(self):
        item = make_item("Kenya financing update", "kenya")
        self.assertEqual(infer_country(item), "kenya")
        self.assertEqual(item.country_priority, "A")
        self.assertEqual(item.country_name_zh, "肯尼亚")

    def test_major_b_plus_can_outrank_ordinary_a(self):
        ordinary_a = make_item("ordinary A", "kenya", score=7.0, source_priority=2.0)
        major_b = make_item("major B+", "ghana", score=9.0, source_priority=2.0)
        selected = balanced_limit([ordinary_a, major_b], limit=1)
        self.assertEqual(selected, [major_b])

    def test_no_country_quota_is_forced(self):
        kenya = [make_item(f"kenya-{i}", "kenya", score=9.0 - i * 0.1) for i in range(4)]
        uganda = make_item("uganda-low", "uganda", score=7.0)
        selected = balanced_limit(kenya + [uganda], limit=3)
        self.assertNotIn(uganda, selected)

    def test_report_wide_cap(self):
        categories = {
            "competitor_product": [make_item("a", "kenya", score=10), make_item("b", "ghana", score=9)],
            "payments_funding": [make_item("c", "nigeria", category="payments_funding", score=8)],
        }
        result = limit_total_items(categories, limit=2)
        titles = [item.title for items in result.values() for item in items]
        self.assertEqual(titles, ["a", "b"])


class FreshnessTests(unittest.TestCase):
    def test_default_window_is_48_hours(self):
        now = datetime.now(timezone.utc)
        recent = make_item("recent", "kenya")
        recent.published = now - timedelta(hours=47)
        old = make_item("old", "kenya")
        old.published = now - timedelta(hours=49)
        self.assertEqual(filter_by_date([recent, old], days=2), [recent])

    def test_official_source_can_use_longer_window(self):
        item = make_item("weekly official", "uganda")
        item.published = datetime.now(timezone.utc) - timedelta(days=5)
        item.freshness_days = 7
        self.assertEqual(filter_by_date([item], days=2), [item])


class SourceConfigTests(unittest.TestCase):
    def setUp(self):
        with (ROOT / "config" / "sources.yaml").open(encoding="utf-8") as file:
            self.config = yaml.safe_load(file)

    def test_markets_match_v2_scope(self):
        markets = self.config["markets"]
        self.assertEqual(set(markets), set(TARGET_COUNTRIES))
        self.assertEqual(
            {key for key, value in markets.items() if value["priority"] == "A"},
            {"kenya", "tanzania", "nigeria"},
        )

    def test_enabled_feeds_have_unique_urls(self):
        enabled = [
            source for source in self.config["rss_sources"].values()
            if source.get("enabled", True)
        ]
        urls = [source["url"] for source in enabled]
        self.assertEqual(len(urls), len(set(urls)))

    def test_all_country_specific_sources_are_in_scope(self):
        for source in self.config["rss_sources"].values():
            country = source.get("country", "multi")
            self.assertIn(country, set(TARGET_COUNTRIES) | {"multi"})

    def test_output_is_three_target_five_cap(self):
        output = self.config["output"]
        self.assertEqual(output["target_items"], 3)
        self.assertEqual(output["max_total_items"], 5)


class PublicOutputTests(unittest.TestCase):
    def setUp(self):
        with (ROOT / "config" / "sources.yaml").open(encoding="utf-8") as file:
            self.config = yaml.safe_load(file)

    def test_three_part_summary_renders(self):
        item = make_item("Sun King financing update", "kenya")
        infer_country(item)
        item.what_happened = "Sun King公布新的手机分期条件。"
        item.why_it_matters = "可用于比较首付与日供门槛。"
        item.scope_limits = "仅适用于公开条款中的指定方案。"
        html = EmailSender().render_email(
            {"competitor_product": [item]},
            {"competitor_product": "竞品与产品"},
            highlights="测试要点",
        )
        self.assertIn("发生了什么", html)
        self.assertIn("为什么值得关注", html)
        self.assertIn("适用边界", html)
        self.assertIn("肯尼亚", html)
        self.assertIn(">A<", html)

    def test_appendix_lists_enabled_sources(self):
        appendix = build_source_appendix(self.config)
        sources = [source for column in appendix["columns"] for source in column]
        enabled_count = sum(
            source.get("enabled", True)
            for source in self.config["rss_sources"].values()
        )
        self.assertEqual(appendix["enabled_count"], enabled_count)
        self.assertEqual(len(sources), enabled_count)
        self.assertTrue(all(source["priority"] for source in sources))


if __name__ == "__main__":
    unittest.main()
