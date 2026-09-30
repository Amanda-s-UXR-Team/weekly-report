"""Shared helpers for the seven-country phone-financing intelligence digest."""

from __future__ import annotations
from math import ceil

COUNTRY_DISPLAY_NAMES = {
    "kenya": "肯尼亚",
    "tanzania": "坦桑尼亚",
    "nigeria": "尼日利亚",
    "uganda": "乌干达",
    "ghana": "加纳",
    "pakistan": "巴基斯坦",
    "bangladesh": "孟加拉国",
    "multi": "跨国",
}

COUNTRY_REPORT_METADATA = {
    "kenya": {"zh": "肯尼亚", "en": "Kenya", "flag": "🇰🇪", "priority": "A"},
    "tanzania": {"zh": "坦桑尼亚", "en": "Tanzania", "flag": "🇹🇿", "priority": "A"},
    "nigeria": {"zh": "尼日利亚", "en": "Nigeria", "flag": "🇳🇬", "priority": "A"},
    "uganda": {"zh": "乌干达", "en": "Uganda", "flag": "🇺🇬", "priority": "B+"},
    "ghana": {"zh": "加纳", "en": "Ghana", "flag": "🇬🇭", "priority": "B+"},
    "pakistan": {"zh": "巴基斯坦", "en": "Pakistan", "flag": "🇵🇰", "priority": "B+"},
    "bangladesh": {"zh": "孟加拉国", "en": "Bangladesh", "flag": "🇧🇩", "priority": "B+"},
    "multi": {"zh": "跨国", "en": "Multi-country", "flag": "🌍", "priority": ""},
}

COUNTRY_ORDER = {
    country: index
    for index, country in enumerate(
        ("kenya", "tanzania", "nigeria", "uganda", "ghana", "pakistan", "bangladesh", "multi")
    )
}

CATEGORY_DISPLAY_NAMES = {
    "competitor_product": "竞品与产品",
    "channel_partnership": "渠道与合作",
    "repayment_risk": "回款与风控",
    "payments_funding": "支付与资金",
    "regulation_enforcement": "监管与实际执行",
    "device_supply_demand": "手机供给与需求",
}

CATEGORY_ORDER = {
    category: index
    for index, category in enumerate(
        (
            "competitor_product",
            "channel_partnership",
            "repayment_risk",
            "payments_funding",
            "regulation_enforcement",
            "device_supply_demand",
        )
    )
}


def sanitize_public_text(value: str | None) -> str:
    return value or ""


def country_priority(country_code: str | None) -> str:
    meta = COUNTRY_REPORT_METADATA.get(country_code or "", {})
    return str(meta.get("priority") or "")


def build_source_appendix(
    config: dict,
    country_code: str | None = None,
    report_days: int = 7,
    max_per_category: int = 5,
    pre_ai_max_per_category: int = 20,
) -> dict:
    configured_sources = config.get("rss_sources", {})
    enabled_sources = []
    applicable_count = 0

    for source_id, source in configured_sources.items():
        source_country = str(source.get("country") or "multi").lower()
        if country_code and source_country not in {country_code, "multi"}:
            continue
        applicable_count += 1
        if not source.get("enabled", True):
            continue

        category_code = str(source.get("category") or "competitor_product").lower()
        priority = float(source.get("priority", 1.0))
        freshness_days = max(int(source.get("freshness_days", report_days)), int(report_days))
        enabled_sources.append(
            {
                "id": source_id,
                "name": sanitize_public_text(str(source.get("name") or source_id)),
                "country": COUNTRY_DISPLAY_NAMES.get(source_country, "跨国"),
                "country_code": source_country,
                "country_priority": country_priority(source_country),
                "category": CATEGORY_DISPLAY_NAMES.get(category_code, category_code),
                "category_code": category_code,
                "priority": f"{priority:.1f}",
                "freshness_days": freshness_days,
            }
        )

    enabled_sources.sort(
        key=lambda source: (
            COUNTRY_ORDER.get(source["country_code"], len(COUNTRY_ORDER)),
            CATEGORY_ORDER.get(source["category_code"], len(CATEGORY_ORDER)),
            -float(source["priority"]),
            source["name"].casefold(),
        )
    )

    midpoint = ceil(len(enabled_sources) / 2)
    return {
        "enabled_count": len(enabled_sources),
        "disabled_count": applicable_count - len(enabled_sources),
        "columns": [enabled_sources[:midpoint], enabled_sources[midpoint:]],
        "weight_rules": [
            {"range": "W3.0", "meaning": "官方监管、一手条款及权威行业来源优先"},
            {"range": "W2.x", "meaning": "可信商业、金融、科技及垂直媒体"},
            {"range": "W1.x", "meaning": "综合或线索型来源，需更强正文证据"},
        ],
        "filter_rules": [
            f"时间：默认近 {report_days} 天；来源可单独配置更长窗口。",
            f"候选：按国家与手机分期经营相关性过滤，AI 前每类最多 {pre_ai_max_per_category} 条，不按国家凑数。",
            "AI：只使用输入证据；草案、试点、公司披露和个案必须标记；缺失信息不得补全。",
            f"成稿：按经营相关度、影响、证据质量和紧迫度排序；整份正常目标3条、最多 {max_per_category} 条。",
        ],
    }
