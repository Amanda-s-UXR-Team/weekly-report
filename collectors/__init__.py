"""RSS-only collectors for the seven-country daily digest."""
from .base import NewsItem, BaseCollector
from .rss_collector import RSSCollector, collect_all_rss
from .article_extractor import OriginalArticleFetcher, enrich_original_articles

__all__ = [
    "NewsItem",
    "BaseCollector",
    "RSSCollector",
    "collect_all_rss",
    "OriginalArticleFetcher",
    "enrich_original_articles",
]
