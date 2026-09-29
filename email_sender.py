"""
HTML/PDF report renderer. Original filename retained; SMTP delivery removed.
"""

from datetime import datetime
from typing import Optional
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

from collectors.base import NewsItem
from reporting import sanitize_public_text

# Try to import weasyprint for PDF generation
try:
    from weasyprint import HTML, CSS
    WEASYPRINT_AVAILABLE = True
except (ImportError, OSError):
    WEASYPRINT_AVAILABLE = False
    print("[PDF] weasyprint not installed, PDF generation disabled")
    print("[PDF] Install with: pip install weasyprint")


class EmailSender:
    """Send HTML emails via SMTP with optional PDF attachment."""

    def __init__(self):
        # Setup Jinja2 template environment
        template_dir = Path(__file__).parent / "templates"
        self.jinja_env = Environment(loader=FileSystemLoader(template_dir))

    def render_email(
        self,
        categories: dict[str, list[NewsItem]],
        category_names: dict[str, str],
        highlights: str = "",
        date_label: str = None,
        **report_context,
    ) -> str:
        """Render email HTML from template."""
        template = self.jinja_env.get_template("email.html")

        # Count total items
        item_count = sum(len(items) for items in categories.values())

        # Render
        html = template.render(
            date=date_label or datetime.now().strftime("%Y年%m月%d日"),
            item_count=item_count,
            highlights=highlights,
            categories=categories,
            category_names=category_names,
            **report_context,
        )

        return sanitize_public_text(html)

    def generate_pdf(self, html_content: str, output_path: str) -> bool:
        """Generate PDF from HTML content."""
        if not WEASYPRINT_AVAILABLE:
            print("[PDF] weasyprint not available, skipping PDF generation")
            return False

        try:
            # PDF-specific CSS adjustments
            # 添加中文字体支持并优化排版（减少空白）
            pdf_css = CSS(string='''
                @page {
                    size: A4;
                    margin: 1cm; /* 减小页边距 */
                }
                body {
                    font-size: 10.5px; /* 稍微减小字号 */
                    line-height: 1.5; /* 减小行高 */
                    font-family: "PingFang SC", "Heiti SC", "Microsoft YaHei", "WenQuanYi Micro Hei", "Noto Sans SC", "Noto Sans CJK SC", "Droid Sans Fallback", "SimSun", sans-serif !important;
                    background-color: #fff;
                }
                .container {
                    max-width: 100% !important;
                    width: 100% !important;
                    margin: 0 !important;
                    box-shadow: none !important;
                }
                .header {
                    padding: 15px 20px !important; /* 减小 Header 内边距 */
                }
                .header h1 {
                    font-size: 24px !important;
                    margin-bottom: 4px !important;
                }
                .highlights {
                    padding: 15px 20px !important; /* 减小 Highlights 内边距 */
                }
                .highlight-item {
                    padding: 10px 15px !important;
                    margin-bottom: 10px !important;
                }
                .category {
                    padding: 15px 20px !important; /* 减小分类内边距 */
                    border-bottom: 1px solid #eee !important;
                }
                .category-header {
                    margin-bottom: 12px !important;
                    font-size: 16px !important;
                    padding-bottom: 8px !important;
                }
                .news-item {
                    padding: 12px !important; /* 减小新闻卡片内边距 */
                    margin-bottom: 12px !important; /* 减小卡片间距 */
                    border: 1px solid #eee !important;
                    box-shadow: none !important;
                    page-break-inside: avoid;
                }
                .news-title {
                    font-size: 14px !important;
                    margin-bottom: 6px !important;
                }
                .news-meta {
                    margin-bottom: 8px !important;
                    font-size: 12px !important;
                }
                .news-summary {
                    font-size: 13px !important;
                    margin-top: 8px !important;
                    line-height: 1.5 !important;
                }
                .news-image {
                    width: 80px !important;
                    height: 60px !important;
                    max-width: 80px !important;
                    max-height: 60px !important;
                    float: right !important;
                    margin-left: 12px !important;
                    margin-bottom: 4px !important;
                }
                .news-content-wrapper {
                    display: block !important; /* override flex for PDF to prevent overlap */
                }
                /* Table of Contents - allow page breaks inside TOC */
                .toc {
                    padding: 15px 20px !important;
                    /* DO NOT use page-break-inside: avoid on TOC
                       — it's too large and causes blank pages */
                }
                .toc h2 {
                    font-size: 14px !important;
                    margin-bottom: 10px !important;
                    page-break-after: avoid; /* keep title with content */
                }
                .toc-list {
                    display: block !important; /* override flex for PDF */
                }
                .toc-category {
                    page-break-inside: avoid;
                    margin-bottom: 8px !important;
                }
                .toc-category-title {
                    font-size: 14px !important;
                    margin-bottom: 6px !important;
                    page-break-after: avoid; /* keep with items below */
                }
                .toc-category-title a {
                    color: #1f2937 !important;
                    text-decoration: none !important;
                }
                .toc-item-link {
                    font-size: 13px !important;
                    margin-bottom: 4px !important;
                }
                .toc-item-link a {
                    color: #4338ca !important;
                    text-decoration: none !important;
                }
                .toc-count {
                    font-size: 11px !important;
                }
                /* Highlights — allow page breaks, keep individual items intact */
                .highlights {
                    /* DO NOT use page-break-inside: avoid here either */
                }
                .highlights h2 {
                    font-size: 16px !important;
                    page-break-after: avoid; /* keep title with first item */
                }
                .highlights-content {
                    display: block !important; /* override flex for PDF */
                }
                /* Ensure internal anchor links work */
                a[href^="#"] {
                    color: #4338ca !important;
                }
                /* Hide footer in PDF to save space */
                .footer {
                    padding: 10px !important;
                    font-size: 10px !important;
                }
                .source-appendix {
                    break-before: page !important;
                    page-break-before: always !important;
                    page-break-inside: avoid !important;
                    padding: 12px 14px !important;
                }
                .source-appendix h2 {
                    font-size: 17px !important;
                    margin-bottom: 3px !important;
                }
                .appendix-kicker {
                    font-size: 8px !important;
                    margin-bottom: 2px !important;
                }
                .appendix-lead {
                    font-size: 8px !important;
                    margin-bottom: 7px !important;
                }
                .appendix-strategy-grid {
                    gap: 7px !important;
                    margin-bottom: 7px !important;
                }
                .appendix-card {
                    padding: 6px 7px !important;
                }
                .appendix-card h3,
                .appendix-source-heading {
                    font-size: 8.5px !important;
                    margin-bottom: 3px !important;
                }
                .appendix-weight,
                .appendix-rule {
                    font-size: 7.6px !important;
                    line-height: 1.3 !important;
                    margin-bottom: 2px !important;
                }
                .appendix-weight strong {
                    min-width: 42px !important;
                }
                .appendix-columns {
                    gap: 8px !important;
                }
                .appendix-source-row {
                    gap: 4px !important;
                    padding: 1.5px 0 !important;
                    font-size: 7.4px !important;
                    line-height: 1.2 !important;
                }
                .appendix-note {
                    font-size: 7px !important;
                    line-height: 1.25 !important;
                    margin-top: 5px !important;
                }
            ''')

            html = HTML(string=html_content)
            html.write_pdf(output_path, stylesheets=[pdf_css])
            print(f"[PDF] Generated: {output_path}")
            return True
        except Exception as e:
            print(f"[PDF] Generation error: {e}")
            return False
