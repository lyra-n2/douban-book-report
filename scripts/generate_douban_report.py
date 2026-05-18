#!/usr/bin/env python3
"""豆瓣读书报告生成器。

通过 Playwright 引导用户登录豆瓣，采集本人「读过/在读/想读」全部数据，
生成单文件 HTML 阅读品味报告。

用法见 SKILL.md。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path


def _check_deps():
    """检测依赖是否就绪，给出带国内镜像的友好提示。"""
    missing = []
    try:
        import playwright  # noqa: F401
    except ImportError:
        missing.append("playwright")
    try:
        import bs4  # noqa: F401
    except ImportError:
        missing.append("beautifulsoup4")
    if missing:
        print("✗ 缺少依赖：" + ", ".join(missing), file=sys.stderr)
        print("\n国内推荐安装方式（清华镜像）：", file=sys.stderr)
        print(f"  pip3 install -i https://pypi.tuna.tsinghua.edu.cn/simple {' '.join(missing)}", file=sys.stderr)
        print("\n再装 Chromium 浏览器（npmmirror 镜像）：", file=sys.stderr)
        print("  PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors python3 -m playwright install chromium", file=sys.stderr)
        sys.exit(1)

STATUSES = [
    ("collect", "读过"),
    ("do", "在读"),
    ("wish", "想读"),
]

PAGE_SIZE = 15
PAGE_SLEEP_SEC = 1.5


def parse_args():
    p = argparse.ArgumentParser(description="豆瓣读书报告生成器")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--login", action="store_true", help="启动浏览器引导用户登录采集")
    src.add_argument("--csv", type=Path, help="解析豆瓣导出的 CSV 文件")
    src.add_argument("--sample", action="store_true", help="使用内置示例数据")
    src.add_argument("--from-raw", type=Path, help="从已保存的 douban-raw-books.json 重建报告，不重新采集")
    p.add_argument("--output", type=Path, default=Path("reports"), help="报告输出目录")
    p.add_argument("--include-comments", action="store_true", help="额外采集每本书的短评（更耗时）")
    p.add_argument("--proxy", default=None, help="HTTP 代理，例如 http://127.0.0.1:7897")
    return p.parse_args()


# ---------- 登录采集模式 ----------

def collect_via_login(proxy: str | None, include_comments: bool) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("缺少依赖：pip install playwright && python3 -m playwright install chromium")

    from bs4 import BeautifulSoup

    with sync_playwright() as pw:
        launch_kwargs = {"headless": False}
        if proxy:
            launch_kwargs["proxy"] = {"server": proxy}
        browser = pw.chromium.launch(**launch_kwargs)
        context = browser.new_context(locale="zh-CN")
        page = context.new_page()

        print("→ 已打开浏览器，正在跳转到豆瓣登录页...")
        page.goto("https://accounts.douban.com/passport/login")

        print("→ 请在弹出窗口中完成登录（扫码或账密均可）。")
        print("  脚本会自动检测登录状态，登录成功后继续。")

        for i in range(180):
            cookies = context.cookies()
            if any(c["name"] == "dbcl2" and c["value"] for c in cookies):
                print("✓ 检测到登录态")
                break
            time.sleep(2)
        else:
            browser.close()
            sys.exit("3 分钟内未检测到登录，已退出。")

        page.goto("https://www.douban.com/mine/")
        page.wait_for_load_state("domcontentloaded")
        uid_match = re.search(r"/people/([^/]+)/", page.url)
        if not uid_match:
            browser.close()
            sys.exit("未检测到登录态，请重试。")
        uid = uid_match.group(1)
        print(f"→ 登录成功，UID: {uid}")

        books: list[dict] = []
        meta_counts: dict[str, int] = {}

        for status_code, status_label in STATUSES:
            print(f"→ 采集 {status_label}...")
            start = 0
            page_count = 0
            while True:
                url = f"https://book.douban.com/people/{uid}/{status_code}?start={start}&sort=time&mode=grid"
                page.goto(url)
                page.wait_for_load_state("domcontentloaded")
                html = page.content()

                if "异常请求" in html or "请输入验证码" in html or "sec.douban.com" in page.url:
                    print("⚠ 触发反爬，请在浏览器窗口中完成验证，脚本将每 5 秒重试...")
                    for _ in range(60):
                        time.sleep(5)
                        page.goto(url)
                        page.wait_for_load_state("domcontentloaded")
                        html = page.content()
                        if "异常请求" not in html and "sec.douban.com" not in page.url:
                            break
                    else:
                        print("⚠ 验证未完成，跳过该状态")
                        break
                    soup = BeautifulSoup(html, "html.parser")
                    items = soup.select("li.subject-item")
                    if not items:
                        break

                soup = BeautifulSoup(html, "html.parser")
                items = soup.select("li.subject-item")
                if not items:
                    break

                for li in items:
                    book = parse_book_item(li, status_code)
                    if book:
                        books.append(book)

                page_count += 1
                start += PAGE_SIZE
                if len(items) < PAGE_SIZE:
                    break
                time.sleep(PAGE_SLEEP_SEC)

            meta_counts[status_code] = sum(1 for b in books if b["status"] == status_code)
            print(f"  共 {meta_counts[status_code]} 本，{page_count} 页")

        browser.close()

    return {
        "meta": {
            "uid": "anonymized",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "total_collect": meta_counts.get("collect", 0),
            "total_doing": meta_counts.get("do", 0),
            "total_wish": meta_counts.get("wish", 0),
        },
        "books": books,
    }


def parse_book_item(li, status_code: str) -> dict | None:
    title_a = li.select_one(".info h2 a")
    if not title_a:
        return None
    title = title_a.get_text(strip=True).replace("\n", "").strip()
    href = title_a.get("href", "")
    book_id_match = re.search(r"/subject/(\d+)/", href)
    book_id = book_id_match.group(1) if book_id_match else None

    pub_el = li.select_one(".pub")
    author = publisher = None
    pub_year = None
    if pub_el:
        parts = [p.strip() for p in pub_el.get_text(strip=True).split("/")]
        if parts:
            author = parts[0]
        if len(parts) >= 3:
            publisher = parts[-3] if len(parts) >= 4 else parts[-2]
        for p in parts:
            ym = re.search(r"(19|20)\d{2}", p)
            if ym:
                pub_year = int(ym.group(0))
                break

    douban_rating = None
    dr_el = li.select_one(".rating-info .rating_nums") or li.select_one(".rating_nums")
    if dr_el:
        try:
            douban_rating = float(dr_el.get_text(strip=True))
        except ValueError:
            pass

    my_rating = None
    for span in li.select(".info span"):
        cls = " ".join(span.get("class", []))
        m = re.search(r"rating(\d)-t", cls)
        if m:
            my_rating = int(m.group(1))
            break

    mark_date = None
    date_el = li.select_one(".date")
    if date_el:
        dm = re.search(r"(\d{4}-\d{2}-\d{2})", date_el.get_text())
        if dm:
            mark_date = dm.group(1)

    tags = []
    tags_el = li.select_one(".tags")
    if tags_el:
        raw = tags_el.get_text(strip=True)
        raw = re.sub(r"^标签[:：]\s*", "", raw)
        tags = [t for t in raw.split() if t]

    comment = None
    comment_el = li.select_one(".comment")
    if comment_el:
        comment = comment_el.get_text(strip=True)

    return {
        "title": title,
        "book_id": book_id,
        "status": status_code,
        "author": author,
        "publisher": publisher,
        "pub_year": pub_year,
        "douban_rating": douban_rating,
        "my_rating": my_rating,
        "mark_date": mark_date,
        "tags": tags,
        "comment": comment,
    }


# ---------- CSV 模式 ----------

def collect_via_csv(path: Path) -> dict:
    books = []
    with path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            books.append({
                "title": row.get("标题") or row.get("title"),
                "book_id": None,
                "status": "collect",
                "author": None,
                "publisher": None,
                "pub_year": None,
                "douban_rating": None,
                "my_rating": _safe_int(row.get("评分") or row.get("my_rating")),
                "mark_date": (row.get("创建时间") or row.get("mark_date") or "")[:10] or None,
                "tags": (row.get("标签") or "").split() if row.get("标签") else [],
                "comment": row.get("备注") or row.get("短评") or row.get("comment"),
            })
    return {
        "meta": {
            "uid": "csv-import",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "total_collect": len(books),
            "total_doing": 0,
            "total_wish": 0,
        },
        "books": books,
    }


def _safe_int(v):
    try:
        return int(v) if v else None
    except (ValueError, TypeError):
        return None


# ---------- 示例数据 ----------

def sample_data() -> dict:
    import random
    random.seed(42)
    read_authors = ["丹尼尔·卡尼曼", "卡尔维诺", "村上春树", "毛姆", "尤瓦尔·赫拉利", "塔勒布", "博尔赫斯", "卡夫卡", "加缪", "陀思妥耶夫斯基"]
    wish_only_authors = ["普里莫·莱维", "安妮·迪拉德", "帕特里克·莫迪亚诺", "汪曾祺", "凯文·凯利", "苏珊·桑塔格", "上野千鹤子"]
    publishers = ["中信出版社", "上海译文出版社", "人民文学出版社", "南海出版公司", "广西师范大学出版社"]
    tags_pool = ["心理学", "哲学", "小说", "认知科学", "历史", "经济学", "随笔", "传记", "科幻", "社会学"]

    books = []
    for i in range(120):
        status = random.choices(["collect", "do", "wish"], weights=[0.8, 0.05, 0.15])[0]
        # 想读列表 60% 概率用 wish-only 作者，更贴近真实场景
        if status == "wish" and random.random() < 0.6:
            author = random.choice(wish_only_authors)
        else:
            author = random.choice(read_authors)
        year = random.randint(2018, 2025)
        month = random.randint(1, 12)
        day = random.randint(1, 28)
        books.append({
            "title": f"示例书籍 {i+1}",
            "book_id": str(1000000 + i),
            "status": status,
            "author": author,
            "publisher": random.choice(publishers),
            "pub_year": random.randint(1980, 2024),
            "douban_rating": round(random.uniform(6.5, 9.5), 1),
            "my_rating": random.randint(2, 5),
            "mark_date": f"{year}-{month:02d}-{day:02d}",
            "tags": random.sample(tags_pool, k=random.randint(1, 3)),
            "comment": None,
        })
    return {
        "meta": {
            "uid": "sample",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "total_collect": sum(1 for b in books if b["status"] == "collect"),
            "total_doing": sum(1 for b in books if b["status"] == "do"),
            "total_wish": sum(1 for b in books if b["status"] == "wish"),
        },
        "books": books,
    }


# ---------- 聚合 ----------

def aggregate(data: dict) -> dict:
    books = data["books"]
    collected = [b for b in books if b["status"] == "collect"]
    wished = [b for b in books if b["status"] == "wish"]
    today = datetime.now().date()

    yearly = Counter()
    monthly_heatmap = Counter()
    for b in collected:
        if b["mark_date"]:
            yearly[b["mark_date"][:4]] += 1
            monthly_heatmap[b["mark_date"][:7]] += 1

    ratings = Counter()
    for b in collected:
        if b["my_rating"]:
            ratings[b["my_rating"]] += 1

    tag_counter = Counter()
    for b in collected:
        for t in b.get("tags", []):
            tag_counter[t] += 1

    author_counter = Counter(b["author"] for b in collected if b["author"])
    publisher_counter = Counter(b["publisher"] for b in collected if b["publisher"])
    pub_year_counter = Counter(b["pub_year"] for b in collected if b["pub_year"])

    yearly_avg_rating = []
    by_year = {}
    for b in collected:
        if b["mark_date"] and b["my_rating"]:
            by_year.setdefault(b["mark_date"][:4], []).append(b["my_rating"])
    for year in sorted(by_year):
        ratings_list = by_year[year]
        yearly_avg_rating.append([year, round(sum(ratings_list) / len(ratings_list), 2), len(ratings_list)])

    # 想读分析
    stale_wishes = []
    for b in wished:
        if b["mark_date"]:
            try:
                d = datetime.strptime(b["mark_date"], "%Y-%m-%d").date()
                days = (today - d).days
                stale_wishes.append({
                    "title": b["title"],
                    "author": b["author"],
                    "mark_date": b["mark_date"],
                    "days": days,
                    "years": round(days / 365, 1),
                })
            except ValueError:
                pass
    stale_wishes.sort(key=lambda x: -x["days"])
    stale_wishes = stale_wishes[:10]

    wish_tag_counter = Counter()
    for b in wished:
        for t in b.get("tags", []):
            wish_tag_counter[t] += 1

    read_authors = {b["author"] for b in collected if b["author"]}
    wish_author_counter = Counter(b["author"] for b in wished if b["author"] and b["author"] not in read_authors)

    common_tags = set(t for t, _ in tag_counter.most_common(15)) | set(t for t, _ in wish_tag_counter.most_common(15))
    tag_compare = []
    for t in common_tags:
        tag_compare.append([t, tag_counter.get(t, 0), wish_tag_counter.get(t, 0)])
    tag_compare.sort(key=lambda x: -(x[1] + x[2]))
    tag_compare = tag_compare[:20]

    return {
        "kpi": {
            "total_collect": data["meta"]["total_collect"],
            "total_doing": data["meta"]["total_doing"],
            "total_wish": data["meta"]["total_wish"],
            "avg_my_rating": round(sum(b["my_rating"] for b in collected if b["my_rating"]) / max(1, sum(1 for b in collected if b["my_rating"])), 2),
        },
        "yearly": sorted(yearly.items()),
        "monthly_heatmap": sorted(monthly_heatmap.items()),
        "ratings": [[i, ratings.get(i, 0)] for i in range(1, 6)],
        "top_tags": tag_counter.most_common(30),
        "tag_radar": tag_counter.most_common(8),
        "top_authors": author_counter.most_common(15),
        "top_publishers": publisher_counter.most_common(10),
        "pub_year_dist": sorted(pub_year_counter.items()),
        "yearly_avg_rating": yearly_avg_rating,
        "stale_wishes": stale_wishes,
        "wish_top_tags": wish_tag_counter.most_common(20),
        "wish_top_authors_not_read": wish_author_counter.most_common(10),
        "tag_compare": tag_compare,
        "generated_at": data["meta"]["generated_at"],
    }


# ---------- HTML 渲染 ----------

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>豆瓣读书报告</title>
<script>
// 多 CDN fallback，国内优先 npmmirror / unpkg
(function loadScript(srcs, onload) {
  if (!srcs.length) { document.getElementById('cdn-warn').style.display = 'block'; return; }
  const s = document.createElement('script');
  s.src = srcs[0];
  s.onload = onload;
  s.onerror = () => { s.remove(); loadScript(srcs.slice(1), onload); };
  document.head.appendChild(s);
})([
  'https://registry.npmmirror.com/echarts/5/files/dist/echarts.min.js',
  'https://unpkg.com/echarts@5/dist/echarts.min.js',
  'https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js',
], () => {
  (function loadWc(srcs) {
    if (!srcs.length) return;
    const s = document.createElement('script');
    s.src = srcs[0];
    s.onload = () => window.dispatchEvent(new Event('echarts-ready'));
    s.onerror = () => { s.remove(); loadWc(srcs.slice(1)); };
    document.head.appendChild(s);
  })([
    'https://registry.npmmirror.com/echarts-wordcloud/2/files/dist/echarts-wordcloud.min.js',
    'https://unpkg.com/echarts-wordcloud@2/dist/echarts-wordcloud.min.js',
    'https://cdn.jsdelivr.net/npm/echarts-wordcloud@2/dist/echarts-wordcloud.min.js',
  ]);
});
</script>
<style>
:root {
  --bg: #f7f3ec;
  --ink: #1a1a1a;
  --blue: #1e3a5f;
  --red: #a83b3b;
  --green: #5a7a3a;
  --gold: #b8860b;
  --muted: #8a8579;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 40px 24px 80px;
  background: var(--bg);
  color: var(--ink);
  font-family: -apple-system, "PingFang SC", "Noto Serif SC", "Songti SC", serif;
  line-height: 1.8;
  max-width: 1080px;
  margin: 0 auto;
}
h1 {
  font-size: 36px;
  font-weight: 700;
  border-bottom: 2px solid var(--ink);
  padding-bottom: 12px;
  margin-bottom: 8px;
}
.subtitle { color: var(--muted); font-size: 14px; margin-bottom: 40px; }
h2 {
  font-size: 24px;
  margin-top: 56px;
  border-left: 6px solid var(--blue);
  padding-left: 14px;
}
h3 { font-size: 18px; margin-top: 32px; color: var(--blue); }
.kpi-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin: 32px 0;
}
.kpi-card {
  background: #fff;
  border: 1px solid #e0d9cc;
  border-radius: 4px;
  padding: 20px;
  text-align: center;
}
.kpi-num { font-size: 32px; font-weight: 700; color: var(--blue); }
.kpi-label { font-size: 14px; color: var(--muted); margin-top: 4px; }
.chart { width: 100%; height: 380px; margin: 16px 0 40px; }
.footer { text-align: center; color: var(--muted); font-size: 12px; margin-top: 80px; }
.stale-list { margin: 16px 0 40px; }
.stale-item {
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 16px; border-bottom: 1px solid #e0d9cc;
}
.stale-item:first-child { border-top: 1px solid #e0d9cc; }
.stale-title { font-weight: 500; }
.stale-meta { color: var(--muted); font-size: 13px; }
.stale-years { color: var(--red); font-weight: 600; min-width: 80px; text-align: right; }
.insights-placeholder {
  background: #fff; border: 1px dashed #c4b89e; border-radius: 4px;
  padding: 24px; margin: 16px 0 40px; color: var(--ink);
}
.insights-placeholder code { background: #f0ead9; padding: 2px 6px; border-radius: 2px; font-size: 13px; }
#insights-content { margin-top: 16px; }
#insights-content h3, #insights-content h4 { color: var(--blue); }
#insights-content table { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 14px; }
#insights-content th, #insights-content td { border: 1px solid #e0d8c8; padding: 8px 10px; text-align: left; }
#insights-content th { background: var(--bg-light, #faf6ee); font-weight: 600; }
#insights-content tr:hover td { background: #faf6ee; }
@media (max-width: 768px) {
  .kpi-row { grid-template-columns: repeat(2, 1fr); }
  body { padding: 20px 12px; }
}
</style>
</head>
<body>

<div id="cdn-warn" style="display:none; background:#fff3cd; border:1px solid #b8860b; padding:12px; margin:16px 0; border-radius:4px;">
  ⚠ 图表 CDN 全部加载失败，可能是网络问题。请检查网络或代理，刷新页面重试。
</div>

<h1>豆瓣读书报告</h1>
<div class="subtitle">生成于 __GENERATED_AT__ · 基于本人豆瓣账号数据 · 仅供个人复盘</div>

<div class="kpi-row">
  <div class="kpi-card"><div class="kpi-num">__KPI_COLLECT__</div><div class="kpi-label">读过</div></div>
  <div class="kpi-card"><div class="kpi-num">__KPI_DOING__</div><div class="kpi-label">在读</div></div>
  <div class="kpi-card"><div class="kpi-num">__KPI_WISH__</div><div class="kpi-label">想读</div></div>
  <div class="kpi-card"><div class="kpi-num">__KPI_AVG__</div><div class="kpi-label">平均评分</div></div>
</div>

<h2>一 · 时间维度</h2>
<h3>年度阅读量</h3>
<div id="chart-yearly" class="chart"></div>
<h3>月度热力</h3>
<div id="chart-monthly" class="chart"></div>

<h2>二 · 品味画像</h2>
<h3>评分分布</h3>
<div id="chart-rating" class="chart"></div>
<h3>分类雷达</h3>
<div id="chart-radar" class="chart"></div>
<h3>标签词云</h3>
<div id="chart-wordcloud" class="chart" style="height: 460px;"></div>

<h2>三 · 偏好作者与出版社</h2>
<h3>Top 作者</h3>
<div id="chart-authors" class="chart" style="height: 460px;"></div>
<h3>Top 出版社</h3>
<div id="chart-publishers" class="chart"></div>

<h2>四 · 书籍特征</h2>
<h3>出版年份分布</h3>
<div id="chart-pubyear" class="chart"></div>

<h2>五 · 想读分析</h2>
<h3>想读但久未读 Top 10</h3>
<div id="chart-stale" class="chart" style="height: 480px;"></div>
<h3>想读但一本都没读过的作者 Top 10</h3>
<div id="chart-wish-authors" class="chart"></div>

<h2>六 · AI 品味洞察</h2>
<div class="insights-placeholder" id="insights-block">
  <p><em>此区块由 Claude 基于你的阅读数据生成，包含品味画像、想读优先级建议和阅读盲区分析。</em></p>
  <p><strong>生成方法</strong>：在 Claude Code 中说「读 <code>__OUTPUT_DIR__/douban-raw-books.json</code>，按 SKILL.md 第 7 步生成洞察并写入 douban-insights.md」，刷新本页即可看到。</p>
  <div id="insights-content"></div>
</div>

<div class="footer">本报告基于本人豆瓣账号数据生成，仅供个人复盘使用。</div>

<script>
window.addEventListener('echarts-ready', () => {
const DATA = __DATA_JSON__;
const TEXT_COLOR = '#1a1a1a';
const BASE = { textStyle: { color: TEXT_COLOR, fontFamily: 'PingFang SC, serif' }, backgroundColor: 'transparent' };

function init(id, opt) {
  const el = document.getElementById(id);
  const chart = echarts.init(el, null, { renderer: 'canvas' });
  chart.setOption(Object.assign({}, BASE, opt));
  window.addEventListener('resize', () => chart.resize());
}

// 年度
init('chart-yearly', {
  grid: { left: 50, right: 30, bottom: 40, top: 30 },
  xAxis: { type: 'category', data: DATA.yearly.map(d => d[0]) },
  yAxis: { type: 'value' },
  series: [{ type: 'bar', data: DATA.yearly.map(d => d[1]), itemStyle: { color: '#1e3a5f' } }],
  tooltip: { trigger: 'axis' },
});

// 月度热力
const months = DATA.monthly_heatmap;
const years = [...new Set(months.map(m => m[0].slice(0,4)))].sort();
const monthLabels = ['1','2','3','4','5','6','7','8','9','10','11','12'];
const heatData = months.map(m => [parseInt(m[0].slice(5,7))-1, years.indexOf(m[0].slice(0,4)), m[1]]);
const maxHeat = Math.max(...months.map(m => m[1]), 1);
init('chart-monthly', {
  tooltip: { position: 'top' },
  xAxis: { type: 'category', data: monthLabels, name: '月' },
  yAxis: { type: 'category', data: years },
  grid: { left: 60, right: 30, bottom: 80, top: 30 },
  visualMap: { min: 0, max: maxHeat, calculable: true, orient: 'horizontal', left: 'center', bottom: 10, itemWidth: 14, itemHeight: 160, inRange: { color: ['#f7f3ec', '#1e3a5f'] } },
  series: [{ type: 'heatmap', data: heatData, label: { show: true, color: '#1a1a1a', fontSize: 11 } }],
});

// 评分
init('chart-rating', {
  grid: { left: 50, right: 30, bottom: 40, top: 30 },
  xAxis: { type: 'category', data: DATA.ratings.map(r => r[0] + '星') },
  yAxis: { type: 'value' },
  series: [{ type: 'bar', data: DATA.ratings.map(r => r[1]), itemStyle: { color: '#a83b3b' } }],
  tooltip: { trigger: 'axis' },
});

// 雷达
const radarMax = Math.max(...DATA.tag_radar.map(t => t[1]), 1);
init('chart-radar', {
  radar: { indicator: DATA.tag_radar.map(t => ({ name: t[0], max: radarMax })), shape: 'polygon' },
  series: [{ type: 'radar', data: [{ value: DATA.tag_radar.map(t => t[1]), areaStyle: { color: 'rgba(30,58,95,0.3)' }, lineStyle: { color: '#1e3a5f' } }] }],
});

// 词云
init('chart-wordcloud', {
  series: [{
    type: 'wordCloud',
    shape: 'circle',
    sizeRange: [14, 56],
    rotationRange: [0, 0],
    gridSize: 8,
    textStyle: { color: () => ['#1e3a5f','#a83b3b','#5a7a3a','#b8860b'][Math.floor(Math.random()*4)] },
    data: DATA.top_tags.map(t => ({ name: t[0], value: t[1] })),
  }],
});

// 作者
init('chart-authors', {
  grid: { left: 110, right: 40, bottom: 30, top: 20 },
  xAxis: { type: 'value' },
  yAxis: { type: 'category', data: DATA.top_authors.map(a => a[0]).reverse(), axisLabel: { width: 100, overflow: 'truncate' } },
  series: [{ type: 'bar', data: DATA.top_authors.map(a => a[1]).reverse(), itemStyle: { color: '#5a7a3a' } }],
  tooltip: { trigger: 'axis' },
});

// 出版社
init('chart-publishers', {
  grid: { left: 130, right: 40, bottom: 30, top: 20 },
  xAxis: { type: 'value' },
  yAxis: { type: 'category', data: DATA.top_publishers.map(a => a[0]).reverse(), axisLabel: { width: 120, overflow: 'truncate' } },
  series: [{ type: 'bar', data: DATA.top_publishers.map(a => a[1]).reverse(), itemStyle: { color: '#b8860b' } }],
  tooltip: { trigger: 'axis' },
});

// 出版年
init('chart-pubyear', {
  grid: { left: 50, right: 30, bottom: 40, top: 30 },
  xAxis: { type: 'category', data: DATA.pub_year_dist.map(d => d[0]) },
  yAxis: { type: 'value' },
  series: [{ type: 'bar', data: DATA.pub_year_dist.map(d => d[1]), itemStyle: { color: '#1e3a5f' } }],
  tooltip: { trigger: 'axis' },
});

// 想读久未读 横向条形图（标签 = 书名 + 作者）
const staleSorted = [...DATA.stale_wishes].reverse();
init('chart-stale', {
  grid: { left: 240, right: 80, bottom: 30, top: 20 },
  xAxis: { type: 'value', name: '想读年数', nameLocation: 'middle', nameGap: 30 },
  yAxis: {
    type: 'category',
    data: staleSorted.map(b => b.title + (b.author ? ' · ' + b.author : '')),
    axisLabel: { width: 230, overflow: 'truncate', fontSize: 12 }
  },
  tooltip: {
    trigger: 'axis', axisPointer: { type: 'shadow' },
    formatter: p => {
      const b = staleSorted[p[0].dataIndex];
      return `<strong>${b.title}</strong><br>${b.author || '—'}<br>标记于 ${b.mark_date}<br>想读 ${b.years} 年`;
    }
  },
  series: [{
    type: 'bar',
    data: staleSorted.map(b => b.years),
    itemStyle: { color: '#a83b3b' },
    label: { show: true, position: 'right', formatter: '{c} 年', color: '#a83b3b', fontWeight: 600 }
  }],
});

// 想读但没读的作者
init('chart-wish-authors', {
  grid: { left: 110, right: 40, bottom: 30, top: 20 },
  xAxis: { type: 'value' },
  yAxis: { type: 'category', data: DATA.wish_top_authors_not_read.map(a => a[0]).reverse(), axisLabel: { width: 100, overflow: 'truncate' } },
  series: [{ type: 'bar', data: DATA.wish_top_authors_not_read.map(a => a[1]).reverse(), itemStyle: { color: '#b8860b' } }],
  tooltip: { trigger: 'axis' },
});

// 加载 AI 洞察（render 时嵌入）
const INSIGHTS_MD = __INSIGHTS_MD__;
if (INSIGHTS_MD) {
  document.querySelector('.insights-placeholder p:first-child').style.display = 'none';
  document.querySelector('.insights-placeholder p:nth-child(2)').style.display = 'none';
  document.getElementById('insights-content').innerHTML = simpleMarkdown(INSIGHTS_MD);
}

function simpleMarkdown(md) {
  return md
    .replace(/^### (.+)$/gm, '<h4>$1</h4>')
    .replace(/^## (.+)$/gm, '<h3>$1</h3>')
    .replace(/^# (.+)$/gm, '<h2>$1</h2>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>.*<\/li>\n?)+/g, m => '<ul>' + m + '</ul>')
    .replace(/\n\n/g, '</p><p>')
    .replace(/^(?!<)/gm, '<p>').replace(/(?<!>)$/gm, '</p>')
    .replace(/<p><(h[234]|ul|li)/g, '<$1').replace(/<\/(h[234]|ul|li)><\/p>/g, '</$1>');
}

});
</script>
</body>
</html>
"""


def _md_tables_to_html(md: str) -> str:
    import re
    lines = md.split("\n")
    out, tbl = [], []

    def flush():
        if len(tbl) >= 2 and re.match(r"^[\s|:-]+$", tbl[1].strip().strip("|")):
            parse = lambda r: [c.strip() for c in r.strip().strip("|").split("|")]
            hdr = parse(tbl[0])
            h = "<table><thead><tr>" + "".join(f"<th>{c}</th>" for c in hdr) + "</tr></thead><tbody>"
            for row in tbl[2:]:
                cells = parse(row)
                h += "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"
            out.append(h + "</tbody></table>")
        else:
            out.extend(tbl)
        tbl.clear()

    for line in lines:
        if line.strip().startswith("|"):
            tbl.append(line)
        else:
            if tbl:
                flush()
            out.append(line)
    if tbl:
        flush()
    return "\n".join(out)


def render_html(agg: dict, output_dir: Path) -> str:
    html = HTML_TEMPLATE
    html = html.replace("__GENERATED_AT__", agg["generated_at"])
    html = html.replace("__KPI_COLLECT__", str(agg["kpi"]["total_collect"]))
    html = html.replace("__KPI_DOING__", str(agg["kpi"]["total_doing"]))
    html = html.replace("__KPI_WISH__", str(agg["kpi"]["total_wish"]))
    html = html.replace("__KPI_AVG__", str(agg["kpi"]["avg_my_rating"]))
    html = html.replace("__OUTPUT_DIR__", str(output_dir.resolve()))
    html = html.replace("__DATA_JSON__", json.dumps(agg, ensure_ascii=False))

    insights_path = output_dir / "douban-insights.md"
    insights_md = insights_path.read_text(encoding="utf-8") if insights_path.exists() else ""
    insights_md = _md_tables_to_html(insights_md)
    html = html.replace("__INSIGHTS_MD__", json.dumps(insights_md, ensure_ascii=False))
    return html


# ---------- 主流程 ----------

def main():
    args = parse_args()

    if args.login:
        _check_deps()
        data = collect_via_login(args.proxy, args.include_comments)
    elif args.csv:
        data = collect_via_csv(args.csv)
    elif args.from_raw:
        data = json.loads(args.from_raw.read_text(encoding="utf-8"))
    else:
        data = sample_data()

    args.output.mkdir(parents=True, exist_ok=True)
    if not args.from_raw:
        (args.output / "douban-raw-books.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    agg = aggregate(data)

    html = render_html(agg, args.output)
    (args.output / "douban-report.html").write_text(html, encoding="utf-8")
    (args.output / "douban-report-data.json").write_text(
        json.dumps(agg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output / "douban-raw-summary.json").write_text(
        json.dumps(data["meta"], ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\n✓ 报告已生成：{args.output / 'douban-report.html'}")

    screenshot_images = capture_screenshots(args.output / "douban-report.html", args.output)
    if screenshot_images:
        print(f"✓ 长图已生成：{screenshot_images[0]}")
        print(f"✓ 分享图已生成（{len(screenshot_images)-1} 张）：")
        for img in screenshot_images[1:]:
            print(f"  - {img}")


def capture_screenshots(html_path: Path, output_dir: Path) -> list:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("\n⚠ 未安装 Playwright，跳过截图生成")
        return []

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1200, "height": 800})
        page.goto(f"file://{html_path.resolve()}")
        page.wait_for_timeout(3000)

        full_path = output_dir / "douban-report-full.png"
        page.screenshot(path=str(full_path), full_page=True)
        results.append(full_path)

        browser.close()

    from PIL import Image
    img = Image.open(str(full_path))
    w, total_h = img.size
    part_count = 4
    part_h = total_h // part_count
    for i in range(part_count):
        y = i * part_h
        h = part_h if i < part_count - 1 else total_h - y
        part = img.crop((0, y, w, y + h))
        part_path = output_dir / f"douban-report-share-{i+1}.png"
        part.save(str(part_path))
        results.append(part_path)
    return results


if __name__ == "__main__":
    main()
