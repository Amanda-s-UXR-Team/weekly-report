#!/usr/bin/env python3
"""Render a clearly labelled synthetic PDF without collection, AI or delivery."""
import sys
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from collectors.base import NewsItem
from email_sender import EmailSender, WEASYPRINT_AVAILABLE
from processors.summarizer import format_structured_highlights

def main():
    if not WEASYPRINT_AVAILABLE:
        raise SystemExit('WeasyPrint/system libraries are missing. See README.')
    renderer = EmailSender()
    item = NewsItem(
        title='离线样例：肯尼亚手机分期条件更新',
        url='https://example.invalid/offline-sample',
        source='人工构造测试样例，不是真实新闻',
        category='competitor_product', country='kenya',
        published=datetime.now(timezone.utc),
        what_happened='某手机分期方案公开了新的首付与还款条件。本条完全是离线人工样例。',
        why_it_matters='用于验证三段式排版，不代表真实市场变化。',
        scope_limits='不是真实新闻，不用于经营判断。',
    )
    categories = {'competitor_product': [item]}
    html = renderer.render_email(
        categories, {'competitor_product': '竞品与产品'},
        format_structured_highlights(categories),
        report_title='手机分期资讯 · 离线排版样例',
        report_subtitle='OFFLINE SAMPLE · 无网络 · 不发送',
        report_icon='',
        highlights_title='今日要点',
        toc_title='今日目录',
        date_label=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y年%m月%d日'),
    )
    out = ROOT / 'output' / 'offline-sample.pdf'
    out.parent.mkdir(parents=True, exist_ok=True)
    if not renderer.generate_pdf(html, str(out)):
        raise SystemExit('PDF generation failed')
    print(out)

if __name__ == '__main__':
    main()
