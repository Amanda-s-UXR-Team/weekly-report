#!/usr/bin/env python3
"""
Seven-Country Info Insights (七国用研洞察)

Collects user-research insights from Russia, India, Indonesia,
Nigeria, Kenya, Pakistan, and Bangladesh — covering macro environment, commerce,
digital ecosystems, pop culture, and mobile markets.

Summarises with DeepSeek AI and pushes PDF-linked cards via Feishu bot.
"""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
load_dotenv()

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from collectors import (
    collect_all_rss,
    NewsItem,
)
from processors import (
    DeepSeekSummarizer,
    finalize_categories,
    infer_country,
    process_items,
)
from email_sender import EmailSender, WEASYPRINT_AVAILABLE
from publishers.feishu_archive import (
    SIX_COUNTRY,
    FeishuArchiveError,
    FeishuArchiveManager,
)
from publishers.feishu_publisher import FeishuPublisher
from publishers.feishu_publisher import FeishuSendError
from reporting import build_source_appendix
from monitoring import (
    new_run_receipt,
    record_delivery,
    require_all_required_primary,
    write_receipt_atomic,
)


REPORT_TIMEZONE = ZoneInfo("Asia/Shanghai")


def report_now() -> datetime:
    """Use Beijing time for report dates, including the 23:00 UTC schedule."""
    return datetime.now(REPORT_TIMEZONE)


def load_config(config_path: str = "config/sources.yaml") -> dict:
    """Load configuration from YAML file."""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


async def collect_all_sources(config: dict) -> list[NewsItem]:
    """Collect news from all configured sources."""
    tasks = []

    # RSS sources (primary collection method)
    if config.get("rss_sources"):
        tasks.append(collect_all_rss(config["rss_sources"]))

    # Run all collectors concurrently
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_items = []
    for result in results:
        if isinstance(result, list):
            all_items.extend(result)
        elif isinstance(result, Exception):
            print(f"Collector error: {result}")

    return all_items


async def main_async():
    """Main entry point (Async)."""
    monitor_receipt = new_run_receipt(
        "seven-country-daily", ["seven-country-daily"]
    )
    write_receipt_atomic(monitor_receipt)
    delivery_required = os.environ.get("REQUIRE_FEISHU_DELIVERY", "").lower() in {
        "1", "true", "yes", "on"
    }
    now = report_now()
    print(f"\n{'='*60}")
    print(f"🔍 七国用研洞察 - {now.strftime('%Y-%m-%d %H:%M')}")
    print(f"   EE1 · India · Indonesia · Nigeria · Kenya · Pakistan · Bangladesh")
    print(f"{'='*60}\n")

    # Load config
    config_path = Path(__file__).parent / "config" / "sources.yaml"
    config = load_config(str(config_path))

    # Get output settings
    output_config = config.get("output", {})
    category_names = output_config.get("category_names", {})
    max_per_category = output_config.get("max_per_category", 15)
    pre_ai_max_per_category = output_config.get(
        "pre_ai_max_per_category",
        max_per_category * 2,
    )
    category_order = output_config.get("category_order", [])

    # Collect from all sources
    print("📡 Collecting from sources...")
    all_items = await collect_all_sources(config)
    print(f"   Total collected: {len(all_items)} items\n")

    if not all_items:
        print("❌ No items collected. Check your configuration and network.")
        return 1

    # Process items (dedupe, filter, group)
    print("🔄 Processing items...")
    categories = process_items(
        all_items,
        max_per_category=pre_ai_max_per_category,
    )
    total_items = sum(len(items) for items in categories.values())
    print(f"   After processing: {total_items} items in {len(categories)} categories\n")

    # AI is required for this daily report. Credentials belong to the new project.
    highlights = ""
    if os.environ.get("DEEPSEEK_API_KEY", "").strip():
        print("🧠 Initializing DeepSeek AI...")
        try:
            summarizer = DeepSeekSummarizer()

            # Semantic dedup BEFORE translation (saves API calls)
            print("🔍 Semantic deduplication...")
            categories = await summarizer.semantic_deduplicate(categories)
            total_items = sum(len(items) for items in categories.values())
            print(f"   After dedup: {total_items} items\n")

            # Translate items in each category
            for cat_name, items in categories.items():
                valid_items, _ = await summarizer.process_and_filter_items(items)
                categories[cat_name] = valid_items

            # Regroup using AI's actual category, balance countries, then cap.
            categories = finalize_categories(
                categories,
                max_per_category=max_per_category,
                category_order=category_order,
            )

            # Generate highlights
            print("✨ Generating daily highlights...")
            highlights = await summarizer.generate_daily_highlights(categories, category_names)
            if summarizer.fatal_error or summarizer.successful_calls == 0:
                raise RuntimeError(summarizer.fatal_error or "No successful AI responses")
            print("   Highlights generated\n")
        except Exception as e:
            print(f"   AI error: {e}\n")
            return 1
    else:
        print("❌ DEEPSEEK_API_KEY is missing; report delivery stopped\n")
        return 1

    # Also enforce final caps if AI was unavailable or failed partway through.
    categories = finalize_categories(
        categories,
        max_per_category=max_per_category,
        category_order=category_order,
    )
    country_counts: dict[str, int] = {}
    for items in categories.values():
        for item in items:
            country = infer_country(item) or "unassigned"
            country_counts[country] = country_counts.get(country, 0) + 1
    print(f"🌍 Final country coverage: {country_counts}\n")

    # Render the shared HTML template and generate the Feishu PDF.
    email_sender = EmailSender()
    source_appendix = build_source_appendix(config)
    html_content = email_sender.render_email(
        categories,
        category_names,
        highlights,
        date_label=now.strftime("%Y年%m月%d日"),
        source_appendix=source_appendix,
    )
    date_str = now.strftime("%Y-%m-%d")
    pdf_path = None

    if WEASYPRINT_AVAILABLE:
        pdf_dir = Path(__file__).parent / "output"
        pdf_dir.mkdir(exist_ok=True)
        pdf_path = str(pdf_dir / f"Seven_Country_Insights_{date_str}.pdf")
        email_sender.generate_pdf(html_content, pdf_path)

    # Publish the PDF-linked digest to Feishu.
    publishers_config = config.get("publishers", {})
    feishu_config = publishers_config.get("feishu", {})

    if feishu_config.get("enabled", False):
        print("\n🚀 Publishing to Feishu...")
        publisher = FeishuPublisher()
        archive = FeishuArchiveManager(publisher)
        if publisher.is_configured():
            title = feishu_config.get("title_format", "🔍 七国用研洞察 - {date}").format(date=date_str)

            # Publish to Feishu Bot (Push)
            bot_config = publishers_config.get("feishu_bot", {})
            if bot_config.get("enabled", False):
                chat_id_str = bot_config.get("chat_id") or os.environ.get("FEISHU_BOT_CHAT_ID")
                if chat_id_str:
                    chat_ids = [cid.strip() for cid in chat_id_str.split(',') if cid.strip()]

                    if chat_ids:
                        first_chat_id = chat_ids[0]
                        doc_url = None

                        # Upload PDF and prepare its group access
                        if pdf_path and Path(pdf_path).exists():
                            try:
                                if archive.is_enabled:
                                    doc_url = await archive.upload_pdf(
                                        pdf_path, title, first_chat_id, SIX_COUNTRY,
                                    )
                                else:
                                    doc_url = await publisher.upload_pdf(
                                        pdf_path, title, first_chat_id,
                                    )
                            except FeishuArchiveError as exc:
                                print(
                                    "   ⚠️ Archive upload failed; using the existing "
                                    f"Feishu upload path: {exc}"
                                )
                                doc_url = await publisher.upload_pdf(
                                    pdf_path,
                                    title,
                                    first_chat_id,
                                )
                            if doc_url:
                                print(f"   PDF available at: {doc_url}")
                        else:
                            print("   ⚠️ PDF not available, skipping Feishu upload")

                        print(f"\n🤖 Pushing to {len(chat_ids)} Feishu Bot Group(s)...")
                        for cid in chat_ids:
                            try:
                                send_receipt = await publisher.send_digest_card(
                                    cid,
                                    title,
                                    highlights,
                                    categories,
                                    category_names,
                                    doc_url,
                                )
                            except FeishuSendError as exc:
                                record_delivery(
                                    monitor_receipt,
                                    "seven-country-daily",
                                    exc.receipt,
                                )
                                write_receipt_atomic(monitor_receipt)
                                raise
                            record_delivery(
                                monitor_receipt,
                                "seven-country-daily",
                                send_receipt,
                            )
                            write_receipt_atomic(monitor_receipt)

                        # Cleanup old documents (older than 180 days)
                        print("\n🧹 Checking for old documents to clean up...")
                        await publisher.cleanup_old_documents()
                    else:
                        print("   ⚠️ Feishu bot enabled but no valid chat IDs found")
                        record_delivery(
                            monitor_receipt,
                            "seven-country-daily",
                            status="not_attempted",
                            error_code="destination_missing",
                        )
                        write_receipt_atomic(monitor_receipt)
                else:
                    print("   ⚠️ Feishu bot enabled but FEISHU_BOT_CHAT_ID not set")
                    record_delivery(
                        monitor_receipt,
                        "seven-country-daily",
                        status="blocked",
                        error_code="destination_missing",
                    )
                    write_receipt_atomic(monitor_receipt)
            else:
                record_delivery(
                    monitor_receipt,
                    "seven-country-daily",
                    status="not_attempted",
                    error_code="delivery_not_attempted",
                )
                write_receipt_atomic(monitor_receipt)
        else:
            print("   ⚠️ Feishu publisher enabled but credentials not found (FEISHU_APP_ID/SECRET)")
            record_delivery(
                monitor_receipt,
                "seven-country-daily",
                status="blocked",
                error_code="credentials_missing",
            )
            write_receipt_atomic(monitor_receipt)
    else:
        record_delivery(
            monitor_receipt,
            "seven-country-daily",
            status="not_attempted",
            error_code="delivery_not_attempted",
        )
        write_receipt_atomic(monitor_receipt)

    require_all_required_primary(monitor_receipt, delivery_required)

    print("\n✅ Daily insights digest completed!")
    return 0


def main():
    """Wrapper for async main."""
    sys.exit(asyncio.run(main_async()))


if __name__ == "__main__":
    sys.exit(main())
