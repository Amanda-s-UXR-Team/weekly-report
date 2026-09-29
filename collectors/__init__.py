"""RSS-only collectors for the seven-country daily digest."""
from .base import NewsItem, BaseCollector
from .rss_collector import RSSCollector, collect_all_rss

__all__ = ["NewsItem", "BaseCollector", "RSSCollector", "collect_all_rss"]
