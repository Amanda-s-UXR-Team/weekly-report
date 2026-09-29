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

def main():
    if not WEASYPRINT_AVAILABLE:
        raise SystemExit('WeasyPrint/system libraries are missing. See README.')
    renderer = EmailSender()
    item = NewsItem(
        title='离线样例：肯尼亚用户关注移动服务体验',
        url='https://example.invalid/offline-sample',
        source='人工构造测试样例，不是真实新闻',
        category='digital_ecosystem', country='kenya',
        published=datetime.now(timezone.utc),
        summary='此内容只用于验证中文字体、摘要排版、原文链接和 PDF 输出。没有采集新闻、调用 AI 或向飞书发送任何内容。',
    )
    html = renderer.render_email(
        {'digital_ecosystem': [item]}, {'digital_ecosystem': '数字生态'},
        '离线排版样例，不代表真实资讯或模型生成结果。',
        report_title='七国日报 · 离线排版样例',
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
