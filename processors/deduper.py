"""
Deduplication, country inference and ranking for the seven-country
phone-financing intelligence digest.
"""

from collections import defaultdict
from datetime import datetime, timezone, timedelta
from collectors.base import NewsItem


TARGET_COUNTRIES = (
    "kenya",
    "tanzania",
    "nigeria",
    "uganda",
    "ghana",
    "pakistan",
    "bangladesh",
)

COUNTRY_PRIORITY = {
    "kenya": "A", "tanzania": "A", "nigeria": "A",
    "uganda": "B+", "ghana": "B+", "pakistan": "B+", "bangladesh": "B+",
}

COUNTRY_NAME_ZH = {
    "kenya": "肯尼亚", "tanzania": "坦桑尼亚", "nigeria": "尼日利亚",
    "uganda": "乌干达", "ghana": "加纳", "pakistan": "巴基斯坦",
    "bangladesh": "孟加拉国", "multi": "跨国",
}

COUNTRY_ALIASES = {
    "kenya": (
        "kenya", "kenyan", "nairobi", "mombasa", "m-pesa", "mpesa",
        "肯尼亚", "内罗毕", "蒙巴萨",
    ),
    "tanzania": (
        "tanzania", "tanzanian", "dar es salaam", "dodoma", "zanzibar",
        "坦桑尼亚", "达累斯萨拉姆", "多多马",
    ),
    "nigeria": (
        "nigeria", "nigerian", "lagos", "abuja", "kano", "naira",
        "尼日利亚", "拉各斯", "阿布贾",
    ),
    "uganda": (
        "uganda", "ugandan", "kampala", "shilling", "umra",
        "乌干达", "坎帕拉",
    ),
    "ghana": (
        "ghana", "ghanaian", "accra", "cedi", "bank of ghana",
        "加纳", "阿克拉",
    ),
    "pakistan": (
        "pakistan", "pakistani", "karachi", "islamabad", "lahore",
        "peshawar", "巴基斯坦", "卡拉奇", "伊斯兰堡", "拉合尔",
    ),
    "bangladesh": (
        "bangladesh", "bangladeshi", "dhaka", "chattogram", "chittagong",
        "taka", "btrc", "孟加拉", "孟加拉国", "达卡", "吉大港",
    ),
}


def infer_country(item: NewsItem) -> str | None:
    """Infer one target country from configured metadata or article text."""
    configured = (item.country or "").strip().lower()
    if configured in TARGET_COUNTRIES or configured == "multi":
        item.country_priority = COUNTRY_PRIORITY.get(configured)
        item.country_name_zh = COUNTRY_NAME_ZH.get(configured)
        return configured

    text = " ".join(
        value for value in (item.title, item.summary, item.content) if value
    ).lower()
    matches = [
        country
        for country, aliases in COUNTRY_ALIASES.items()
        if any(alias in text for alias in aliases)
    ]
    if len(matches) == 1:
        item.country = matches[0]
        item.country_priority = COUNTRY_PRIORITY.get(matches[0])
        item.country_name_zh = COUNTRY_NAME_ZH.get(matches[0])
        return matches[0]
    if len(matches) > 1:
        item.country = "multi"
        item.country_priority = None
        item.country_name_zh = COUNTRY_NAME_ZH["multi"]
        return "multi"
    return None


def item_matches_country(item: NewsItem, country: str) -> bool:
    country = country.strip().lower()
    if country not in TARGET_COUNTRIES:
        return False
    configured = (item.country or "").strip().lower()
    if configured == country:
        return True
    if configured and configured != "multi":
        return False
    text = " ".join(
        value for value in (item.title, item.summary, item.content) if value
    ).lower()
    return any(alias in text for alias in COUNTRY_ALIASES[country])


def _item_rank_key(item: NewsItem) -> tuple[float, float, float, float]:
    published = item.published
    if published and published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    timestamp = published.timestamp() if published else 0.0
    editorial = float(
        getattr(item, "editorial_score", 0.0)
        or getattr(item, "relevance_score", 0.0)
        or 0.0
    )
    source_priority = float(getattr(item, "source_priority", 1.0) or 1.0)
    country = infer_country(item)
    country_tiebreak = 1.0 if COUNTRY_PRIORITY.get(country) == "A" else 0.0
    # Business/editorial value dominates. A/B+ is only a tie-breaker, so a major
    # B+ event can outrank an ordinary A-market item.
    return (editorial, source_priority, country_tiebreak, timestamp)


def balanced_limit(items: list[NewsItem], limit: int | None) -> list[NewsItem]:
    """Compatibility name: rank globally; never force one item per country."""
    ranked = sorted(items, key=_item_rank_key, reverse=True)
    return ranked if not limit else ranked[:limit]


def deduplicate_items(items: list[NewsItem]) -> list[NewsItem]:
    seen_urls = set()
    seen_titles = set()
    unique_items = []
    for item in items:
        url_key = (item.url or "").strip()
        title_key = " ".join((item.title or "").lower().split())[:80]
        if url_key and url_key in seen_urls:
            continue
        if title_key and title_key in seen_titles:
            continue
        if url_key:
            seen_urls.add(url_key)
        if title_key:
            seen_titles.add(title_key)
        unique_items.append(item)
    return unique_items


def filter_by_date(items: list[NewsItem], days: float = 2.0) -> list[NewsItem]:
    """Default to a 48-hour news window; source-specific windows can be longer."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    filtered = []
    for item in items:
        if item.published:
            pub_date = item.published
            if pub_date.tzinfo is None:
                pub_date = pub_date.replace(tzinfo=timezone.utc)
            target_cutoff = (
                now - timedelta(days=float(item.freshness_days))
                if item.freshness_days is not None
                else cutoff
            )
            if pub_date >= target_cutoff:
                filtered.append(item)
        else:
            # Undated RSS items are kept as candidates; the AI prompt is required
            # to flag missing dates rather than invent them.
            filtered.append(item)
    return filtered


def sort_items(items: list[NewsItem], by: str = "published") -> list[NewsItem]:
    if by == "published":
        return sorted(
            items,
            key=lambda x: x.published or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
    if by == "score":
        return sorted(items, key=_item_rank_key, reverse=True)
    return items


def group_by_category(items: list[NewsItem]) -> dict[str, list[NewsItem]]:
    grouped = defaultdict(list)
    for item in items:
        grouped[item.category].append(item)
    return dict(grouped)


def process_items(
    items: list[NewsItem],
    max_per_category: int = 20,
    days: float = 2.0,
    apply_date_filter: bool = True,
) -> dict[str, list[NewsItem]]:
    items = deduplicate_items(items)
    if apply_date_filter:
        items = filter_by_date(items, days=days)

    # Reject explicitly out-of-scope configured countries before AI processing.
    scoped = []
    for item in items:
        country = infer_country(item)
        if country in TARGET_COUNTRIES or country == "multi":
            scoped.append(item)
    grouped = group_by_category(sort_items(scoped, by="published"))
    for category in grouped:
        grouped[category] = balanced_limit(grouped[category], max_per_category)
    return grouped


def finalize_categories(
    categories: dict[str, list[NewsItem]],
    max_per_category: int,
    category_order: list[str] | None = None,
) -> dict[str, list[NewsItem]]:
    """Regroup AI-classified items and rank without country quotas."""
    regrouped: dict[str, list[NewsItem]] = defaultdict(list)
    for items in categories.values():
        for item in items:
            country = infer_country(item)
            if country in TARGET_COUNTRIES or country == "multi":
                regrouped[item.category].append(item)

    ordered_categories = list(category_order or [])
    ordered_categories.extend(
        category for category in regrouped if category not in ordered_categories
    )
    result: dict[str, list[NewsItem]] = {}
    for category in ordered_categories:
        items = regrouped.get(category, [])
        if items:
            result[category] = balanced_limit(items, max_per_category)
    return result


def limit_total_items(
    categories: dict[str, list[NewsItem]],
    limit: int = 5,
    category_order: list[str] | None = None,
) -> dict[str, list[NewsItem]]:
    """Apply the report-wide cap after AI scoring; do not fill quotas."""
    all_items = [item for items in categories.values() for item in items]
    selected = balanced_limit(all_items, limit)
    selected_ids = {id(item) for item in selected}
    order = list(category_order or categories.keys())
    order.extend(k for k in categories if k not in order)
    return {
        category: [item for item in categories.get(category, []) if id(item) in selected_ids]
        for category in order
        if any(id(item) in selected_ids for item in categories.get(category, []))
    }
