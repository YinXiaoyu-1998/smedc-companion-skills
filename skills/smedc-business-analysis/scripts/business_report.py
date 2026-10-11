"""Business diagnosis presentation backed only by SMEDC-derived facts."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from statistics import median
from typing import Any

from identity import organization_name_from_metadata
from report_common import human_gap_messages, store_bucket


def read_facts(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    for row in rows:
        for key, value in row.items():
            if value in (None, ""):
                row[key] = None
            elif key not in {"门店名称", "餐段", "时段", "城市", "商户号", "订单分类", "订单来源", "月", "会员类型", "支付/来源"}:
                try:
                    row[key] = float(value)
                except ValueError:
                    pass
    return rows


def complete(row: dict[str, Any], *fields: str) -> bool:
    return all(isinstance(row.get(field), (int, float)) for field in fields)


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    low = int(index)
    return ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low]) * (index - low)


def classify_stores(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Segment stores against the available tenant-neutral store set."""
    groups = defaultdict(list)
    for row in rows:
        row = {**row, "short_name": row["门店名称"], "store_size": store_bucket(row["门店名称"])}
        groups[row["store_size"]].append(row)
    output = []
    for bucket, stores in groups.items():
        eligible = [r for r in stores if complete(r, "net_revenue", "post_discount_aov", "discount_rate")]
        for row in stores:
            segment, action = "数据不足", "补齐经营指标后再判断"
            if row in eligible:
                revenue = row["net_revenue"]
                aov = row["post_discount_aov"]
                discount = row["discount_rate"]
                revenues = [r["net_revenue"] for r in eligible]
                aovs = [r["post_discount_aov"] for r in eligible]
                discounts = [r["discount_rate"] for r in eligible]
                if revenue >= percentile(revenues, .75) and aov >= median(aovs):
                    segment, action = "明星店", "验证并复制高客单与高收入打法"
                elif revenue >= median(revenues):
                    segment, action = "稳定现金流", "守住收入，检查折扣纪律"
                elif discount > median(discounts) or aov < median(aovs):
                    segment, action = "结构机会店", "优先检查客单、折扣或渠道结构"
                else:
                    segment, action = "低效待改善", "用门店辅导改善基础经营"
            output.append({**row, "segment": segment, "action": action})
    return output


def opportunities(stores: list[dict[str, Any]], channels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Opportunity scenarios; omit estimates without their required facts."""
    definitions = [
        ("折扣纪律", "discount_rate", "gross_sales", True, "高折扣门店回到全体门店中位折扣率", "运营 + 门店督导"),
        ("低客单修复", "post_discount_aov", "positive_orders", False, "低客单门店追平全体门店中位折后单均", "菜单 + 门店"),
        ("会员渗透补齐", "member_revenue_share", "net_revenue", False, "低会员占比门店追平全体门店中位会员收入占比", "会员运营"),
    ]
    result = []
    for name, metric, weight, high, logic, owner in definitions:
        groups = defaultdict(list)
        for row in stores:
            if complete(row, metric, weight):
                groups["全体门店"].append(row)
        if not groups:
            continue
        amount = 0.0
        for group in groups.values():
            benchmark = median([row[metric] for row in group])
            amount += sum(max(0, row[metric] - benchmark if high else benchmark - row[metric]) * row[weight] for row in group)
        result.append({"name": name, "value": round(amount / 10000, 1), "unit": "万元会员收入池" if metric == "member_revenue_share" else "万元",
                       "confidence": "情景测算", "effort": "中", "logic": logic, "owner": owner})
    delivery = [r for r in channels if any(word in str(r.get("订单分类")) + str(r.get("订单来源")) for word in ("外卖", "闪购", "秒送"))
                and complete(r, "discount_rate", "gross_sales")]
    if delivery:
        amount = sum(max(0, r["discount_rate"] - .18) * r["gross_sales"] for r in delivery)
        result.append({"name": "外卖折扣治理", "value": round(amount / 10000, 1), "unit": "万元", "confidence": "情景测算", "effort": "高",
                       "logic": "假设高折扣外卖渠道回落到 18% 折扣率；该值是测算假设", "owner": "外卖运营"})
    return result


def build_payload(input_dir: Path) -> dict[str, Any]:
    summary = json.loads((input_dir / "analysis_summary.json").read_text(encoding="utf-8"))
    overall = summary["overall_kpis"]
    stores = classify_stores(read_facts(input_dir / "store_summary.csv"))
    channels = read_facts(input_dir / "channel_summary.csv")
    dayparts = read_facts(input_dir / "daypart_summary.csv")
    monthly = read_facts(input_dir / "monthly_trend.csv")
    members = read_facts(input_dir / "member_summary.csv")
    has_current = any(complete(row, "net_revenue") for row in [overall, *stores])
    insights = []
    if has_current:
        if complete(overall, "dine_in_revenue_share", "delivery_revenue_share"):
            insights.append({"label": "收入结构", "title": "店内与外卖收入贡献", "metric": f"{overall['dine_in_revenue_share']:.1%}",
                             "note": f"店内收入占比；外卖占比 {overall['delivery_revenue_share']:.1%}。"})
        if complete(overall, "discount_rate", "discount_amount"):
            insights.append({"label": "收入质量", "title": "关注优惠规模与渠道折扣", "metric": f"{overall['discount_rate']:.1%}",
                             "note": f"期间优惠金额 {overall['discount_amount'] / 10000:,.1f} 万元。"})
        group = [row for row in stores if complete(row, "net_revenue")]
        if group:
            top = max(group, key=lambda r: r["net_revenue"])
            insights.append({"label": "门店收入", "title": "收入领先门店", "metric": top["short_name"],
                             "note": f"订单营业收入 {top['net_revenue'] / 10000:,.1f} 万元；按全体门店比较。"})
        timed = [r for r in dayparts if r.get("时段") not in (None, "全部时段", "未知时段") and complete(r, "net_revenue")]
        if timed:
            top = max(timed, key=lambda r: r["net_revenue"])
            insights.append({"label": "餐段机会", "title": "收入最高的餐段与时段", "metric": f"{top['餐段']} {top['时段']}",
                             "note": f"订单营业收入 {top['net_revenue'] / 10000:,.1f} 万元；结合门店运营验证原因。"})
    pool = opportunities(stores, channels) if has_current else []
    availability = {"current": has_current, "summary": bool(insights), "baseline": has_current,
                    "stores": has_current and bool(stores), "channels": has_current and bool(channels or members),
                    "dayparts": has_current and any(r.get("时段") not in (None, "全部时段", "未知时段") for r in dayparts),
                    "opportunities": bool(pool)}
    messages = human_gap_messages(summary.get("notices", []))
    for available, message in (
        (any(complete(r, "net_revenue") for r in monthly), "缺少月度营业数据，趋势图未展示。"),
        (availability["dayparts"], "缺少时段数据，时段分析未展示。"),
        (availability["channels"], "缺少渠道与会员数据，相关分析未展示。"),
    ):
        if not available:
            messages.append(message)
    if not has_current:
        messages = [
            "所选店名在本期没有匹配的营业数据，经营指标与分析板块未展示。"
            if summary["source"].get("store_name_contains") else "本期暂无可用经营数据，经营指标与分析板块未展示。"
        ]
    window = summary["source"]["windows"]["current"]
    company = organization_name_from_metadata(summary)
    scope = summary["source"].get("store_name_contains", [])
    period = f"{window['start']}—{window['end']}"
    if scope:
        period += f"｜门店名称包含：{'、'.join(scope)}（全体门店为筛选后合计）"
    return {"meta": {"title": f"{company}经营诊断报告", "company": company, "period": period,
                     "generated": date.today().isoformat(), "store_count": len(stores),
                     "store_name_contains": summary["source"].get("store_name_contains", [])},
            "overall": overall, "insights": insights, "stores": stores, "channels": channels,
            "monthly": monthly, "dayparts": dayparts, "members": members,
            "store_segments": dict(Counter(row["segment"] for row in stores)), "opportunities": pool,
            "availability": availability, "data_gaps": list(dict.fromkeys(messages))}


# Presentation ported from the original business-analysis report.
HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>__REPORT_TITLE__</title>
  <style>
    :root {
      --bg: #f6f8fb;
      --surface: #ffffff;
      --surface-2: #eef3f4;
      --ink: #18212f;
      --muted: #627083;
      --line: #d9e1e7;
      --teal: #006d77;
      --teal-2: #83c5be;
      --blue: #355c9f;
      --amber: #b85c00;
      --orange: #d96b3b;
      --green: #3a7d44;
      --red: #b23a48;
      --violet: #7757a6;
      --shadow: 0 18px 45px rgba(24, 33, 47, 0.08);
      --radius: 8px;
    }
    [hidden] { display: none !important; }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      color: var(--ink);
      background: var(--bg);
      font: 14px/1.55 Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      letter-spacing: 0;
    }
    a { color: inherit; text-decoration: none; }
    button, select { font: inherit; }
    .shell { min-height: 100vh; }
    .topbar {
      position: sticky;
      top: 0;
      z-index: 10;
      background: rgba(246, 248, 251, 0.94);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(14px);
    }
    .topbar-inner {
      max-width: 1360px;
      margin: 0 auto;
      padding: 12px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 24px;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 250px;
      font-weight: 760;
    }
    .brand-mark {
      width: 32px;
      height: 32px;
      border-radius: 8px;
      background: conic-gradient(from 140deg, var(--teal), var(--blue), var(--amber), var(--teal));
      box-shadow: 0 8px 20px rgba(0, 109, 119, 0.18);
    }
    .nav {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      flex-wrap: wrap;
      gap: 4px;
    }
    .nav a, .pill-button {
      border: 1px solid transparent;
      border-radius: 999px;
      padding: 7px 11px;
      color: var(--muted);
      background: transparent;
      cursor: pointer;
    }
    .nav a:hover, .pill-button:hover, .pill-button.active {
      color: var(--ink);
      border-color: var(--line);
      background: var(--surface);
    }
    main { max-width: 1360px; margin: 0 auto; padding: 28px 24px 64px; }
    .hero {
      display: grid;
      grid-template-columns: minmax(0, 1.15fr) minmax(320px, 0.85fr);
      gap: 28px;
      align-items: stretch;
      padding: 28px 0 18px;
    }
    .hero h1 {
      margin: 0 0 12px;
      font-size: 40px;
      line-height: 1.12;
      font-weight: 800;
    }
    .hero-sub {
      max-width: 780px;
      margin: 0;
      color: var(--muted);
      font-size: 16px;
    }
    .hero-meta {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 22px;
    }
    .meta-chip {
      padding: 8px 10px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--surface);
      color: var(--muted);
    }
    .score-panel {
      background: var(--ink);
      color: #fff;
      border-radius: var(--radius);
      padding: 22px;
      box-shadow: var(--shadow);
      display: grid;
      gap: 18px;
    }
    .score-label { color: rgba(255,255,255,0.7); font-size: 13px; }
    .score-value { font-size: 34px; font-weight: 820; line-height: 1; margin-top: 6px; }
    .score-row {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
    }
    .score-mini {
      background: rgba(255,255,255,0.08);
      border: 1px solid rgba(255,255,255,0.12);
      border-radius: 8px;
      padding: 12px;
    }
    .score-mini b { display: block; margin-top: 3px; font-size: 18px; }
    .section {
      padding: 34px 0;
      border-top: 1px solid var(--line);
    }
    .section-head {
      display: flex;
      justify-content: space-between;
      gap: 20px;
      align-items: end;
      margin-bottom: 18px;
    }
    .section-kicker {
      color: var(--teal);
      font-size: 13px;
      font-weight: 760;
      text-transform: uppercase;
    }
    .section h2 {
      margin: 3px 0 0;
      font-size: 26px;
      line-height: 1.22;
    }
    .section-note { margin: 0; color: var(--muted); max-width: 600px; }
    .grid-4 { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
    .grid-3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
    .grid-2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
    .tile, .panel, .insight {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: 0 10px 28px rgba(24, 33, 47, 0.045);
    }
    .tile { padding: 16px; min-height: 136px; }
    .tile-label { color: var(--muted); font-size: 12px; font-weight: 700; }
    .tile-value { margin-top: 8px; font-size: 28px; font-weight: 820; line-height: 1; }
    .tile-foot { margin-top: 12px; color: var(--muted); font-size: 13px; }
    .insight { padding: 16px; display: grid; gap: 10px; }
    .insight-top { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
    .insight-label { color: var(--muted); font-size: 12px; font-weight: 720; }
    .insight-metric { font-size: 24px; font-weight: 820; color: var(--teal); }
    .insight-title { font-size: 16px; font-weight: 760; line-height: 1.35; }
    .insight-note { color: var(--muted); font-size: 13px; }
    .panel { padding: 18px; min-width: 0; }
    .panel-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      margin-bottom: 10px;
    }
    .panel-title { font-size: 16px; font-weight: 780; }
    .panel-caption { margin-top: 2px; color: var(--muted); font-size: 12px; }
    .control-row { display: flex; gap: 6px; flex-wrap: wrap; }
    .chart { width: 100%; min-height: 300px; position: relative; overflow: hidden; }
    .chart svg { width: 100%; height: 100%; min-height: 300px; display: block; overflow: hidden; }
    .legend { display: flex; gap: 12px; flex-wrap: wrap; color: var(--muted); font-size: 12px; margin-top: 10px; }
    .legend-item { display: inline-flex; align-items: center; gap: 6px; }
    .swatch { width: 10px; height: 10px; border-radius: 2px; }
    .tooltip {
      position: fixed;
      z-index: 50;
      pointer-events: none;
      background: #111827;
      color: #fff;
      border-radius: 6px;
      padding: 8px 10px;
      font-size: 12px;
      box-shadow: var(--shadow);
      opacity: 0;
      transform: translate(-50%, -120%);
      transition: opacity .12s ease;
      max-width: 260px;
    }
    .segment-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
    }
    .segment {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      background: var(--surface-2);
    }
    .segment b { display: block; font-size: 22px; margin: 6px 0; }
    .table-wrap {
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: var(--surface);
    }
    table { width: 100%; border-collapse: collapse; min-width: 780px; }
    th, td { padding: 11px 12px; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap; }
    th { position: sticky; top: 0; background: #f1f5f8; color: var(--muted); font-size: 12px; cursor: pointer; }
    td { font-size: 13px; }
    tr:last-child td { border-bottom: 0; }
    .tag {
      display: inline-flex;
      align-items: center;
      padding: 4px 8px;
      border-radius: 999px;
      background: #edf3f0;
      color: var(--teal);
      font-size: 12px;
      font-weight: 720;
    }
    .matrix {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }
    .opportunity {
      padding: 16px;
      border: 1px solid var(--line);
      background: var(--surface);
      border-radius: var(--radius);
    }
    .opportunity .value { font-size: 26px; font-weight: 820; margin: 10px 0 4px; }
    .opportunity .logic { color: var(--muted); min-height: 40px; }
    .owner { margin-top: 12px; font-size: 12px; color: var(--muted); }
    .callout {
      border-left: 4px solid var(--amber);
      background: #fff8ef;
      padding: 14px 16px;
      border-radius: 0 8px 8px 0;
      color: #61420f;
    }
    .footer {
      color: var(--muted);
      border-top: 1px solid var(--line);
      padding-top: 18px;
      display: flex;
      justify-content: space-between;
      gap: 20px;
      flex-wrap: wrap;
    }
    @media (max-width: 980px) {
      .hero, .grid-2, .grid-3 { grid-template-columns: 1fr; }
      .grid-4, .segment-grid, .matrix { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .topbar-inner { align-items: flex-start; flex-direction: column; }
      .nav { justify-content: flex-start; }
    }
    @media (max-width: 620px) {
      main { padding: 18px 14px 48px; }
      .hero h1 { font-size: 30px; }
      .grid-4, .segment-grid, .matrix, .score-row { grid-template-columns: 1fr; }
      .section-head { align-items: start; flex-direction: column; }
      .brand { min-width: 0; }
    }
  </style>
</head>
<body>
  <div class="tooltip" id="tooltip"></div>
  <div class="shell">
    <header class="topbar">
      <div class="topbar-inner">
        <a class="brand" href="#top" aria-label="返回顶部">
          <span class="brand-mark" aria-hidden="true"></span>
          <span>__NAV_TITLE__</span>
        </a>
        <nav class="nav" aria-label="报告导航">
          <a href="#summary">结论</a>
          <a href="#baseline">基线</a>
          <a href="#stores">门店</a>
          <a href="#channels">渠道</a>
          <a href="#dayparts">餐段</a>
          <a href="#opportunities">机会</a>
        </nav>
      </div>
    </header>

    <main id="top">
      <section class="hero" aria-labelledby="report-title">
        <div>
          <div class="section-kicker">Management Diagnosis</div>
          <h1 id="report-title">__REPORT_TITLE__</h1>
          <p class="hero-sub">基于营业分组数据形成第一版经营事实底稿，聚焦收入质量、门店组合、渠道结构、餐段机会与可执行经营杠杆。</p>
          <div class="hero-meta">
            <span class="meta-chip">周期：__PERIOD__</span>
            <span class="meta-chip">门店：__STORE_COUNT__ 家</span>
          </div>
        </div>
        <aside class="score-panel" aria-label="核心经营规模">
          <div>
            <div class="score-label">订单营业收入</div>
            <div class="score-value" data-format="wan" data-value="__NET_REVENUE__">0</div>
          </div>
          <div class="score-row">
            <div class="score-mini"><span class="score-label">营业额</span><b data-format="wan" data-value="__GROSS_SALES__"></b></div>
            <div class="score-mini"><span class="score-label">折扣率</span><b data-format="pct" data-value="__DISCOUNT_RATE__"></b></div>
            <div class="score-mini"><span class="score-label">折后单均</span><b data-format="yuan" data-value="__POST_DISCOUNT_AOV__"></b></div>
          </div>
        </aside>
      </section>

      __DATA_NOTICE__
      <section class="section" id="summary">
        <div class="section-head">
          <div>
            <div class="section-kicker">01 Executive Summary</div>
            <h2>先看经营事实，再选择追踪方向</h2>
          </div>
          <p class="section-note">每条结论都来自聚合事实表；下一轮可用访谈和成本数据验证根因。</p>
        </div>
        <div class="grid-4" id="insightGrid"></div>
      </section>

      <section class="section" id="baseline">
        <div class="section-head">
          <div>
            <div class="section-kicker">02 Baseline</div>
            <h2>收入基线：规模、趋势与折扣</h2>
          </div>
          <div class="control-row" role="group" aria-label="趋势指标">
            <button class="pill-button active" data-month-metric="net_revenue">收入</button>
            <button class="pill-button" data-month-metric="positive_orders">订单</button>
            <button class="pill-button" data-month-metric="discount_rate">折扣率</button>
          </div>
        </div>
        <div class="grid-4">
          <div class="tile"><div class="tile-label">营业额</div><div class="tile-value" data-format="wan" data-value="__GROSS_SALES__"></div><div class="tile-foot">折前口径</div></div>
          <div class="tile"><div class="tile-label">订单营业收入</div><div class="tile-value" data-format="wan" data-value="__NET_REVENUE__"></div><div class="tile-foot">用于经营主线</div></div>
          <div class="tile"><div class="tile-label">优惠金额</div><div class="tile-value" data-format="wan" data-value="__DISCOUNT_AMOUNT__"></div><div class="tile-foot">期间折扣池</div></div>
          <div class="tile"><div class="tile-label">正向订单</div><div class="tile-value" data-format="count" data-value="__POSITIVE_ORDERS__"></div><div class="tile-foot">正向订单口径</div></div>
        </div>
        <div class="grid-2" style="margin-top:16px;">
          <div class="panel">
            <div class="panel-head">
              <div><div class="panel-title">月度经营趋势</div><div class="panel-caption">支持切换收入、订单、折扣率</div></div>
            </div>
            <div class="chart" id="monthlyChart"></div>
          </div>
          <div class="panel">
            <div class="panel-head">
              <div><div class="panel-title">收入结构</div><div class="panel-caption">店内、外卖、自提按订单营业收入拆分</div></div>
            </div>
            <div class="chart" id="mixChart"></div>
            <div class="legend" id="mixLegend"></div>
          </div>
        </div>
      </section>

      <section class="section" id="stores">
        <div class="section-head">
          <div>
            <div class="section-kicker">03 Store Portfolio</div>
            <h2>门店组合：同规模比较收入与客单</h2>
          </div>
          <p class="section-note">门店分型基于收入、折后单均、折扣率和收入结构，适合作为经营会的讨论起点。</p>
        </div>
        <label>门店规模 <select id="storeSizeSelect" aria-label="门店规模"></select></label>
        <div class="grid-2">
          <div class="panel">
            <div class="panel-head">
              <div><div class="panel-title">门店收入排名</div><div class="panel-caption">点击切换收入、折扣率、客单</div></div>
              <div class="control-row">
                <button class="pill-button active" data-store-metric="net_revenue">收入</button>
                <button class="pill-button" data-store-metric="discount_rate">折扣</button>
                <button class="pill-button" data-store-metric="post_discount_aov">客单</button>
              </div>
            </div>
            <div class="chart" id="storeBarChart"></div>
          </div>
          <div class="panel">
            <div class="panel-head">
              <div><div class="panel-title">收入 vs 折后单均</div><div class="panel-caption">气泡越大，折扣率越高</div></div>
            </div>
            <div class="chart" id="storeScatter"></div>
          </div>
        </div>
        <div class="segment-grid" id="segmentGrid" style="margin-top:16px;"></div>
        <div class="table-wrap" style="margin-top:16px;">
          <table id="storeTable">
            <thead>
              <tr>
                <th data-sort="short_name">门店</th>
                <th data-sort="segment">分型</th>
                <th data-sort="net_revenue">收入</th>
                <th data-sort="discount_rate">折扣率</th>
                <th data-sort="post_discount_aov">折后单均</th>
                <th data-sort="delivery_revenue_share">外卖占比</th>
                <th data-sort="member_revenue_share">会员占比</th>
                <th>动作</th>
              </tr>
            </thead>
            <tbody></tbody>
          </table>
        </div>
      </section>

      <section class="section" id="channels">
        <div class="section-head">
          <div>
            <div class="section-kicker">04 Channel Quality</div>
            <h2>渠道结构：对比收入贡献、客单与折扣强度</h2>
          </div>
          <p class="section-note">渠道诊断优先看三件事：收入贡献、折后单均、折扣率。</p>
        </div>
        <div class="grid-2">
          <div class="panel">
            <div class="panel-head">
              <div><div class="panel-title">渠道收入与折扣率</div><div class="panel-caption">条形为收入，圆点为折扣率</div></div>
            </div>
            <div class="chart" id="channelChart"></div>
          </div>
          <div class="panel">
            <div class="panel-head">
              <div><div class="panel-title">会员与非会员</div><div class="panel-caption">对比会员与非会员收入贡献</div></div>
            </div>
            <div class="chart" id="memberChart"></div>
          </div>
        </div>
      </section>

      <section class="section" id="dayparts">
        <div class="section-head">
          <div>
            <div class="section-kicker">05 Daypart Opportunity</div>
            <h2>餐段机会：用时段热力图定位高峰与折扣压力</h2>
          </div>
          <p class="section-note">热力图按餐段和时段展示订单营业收入，深色表示收入高。</p>
        </div>
        <div class="grid-2">
          <div class="panel">
            <div class="panel-head">
              <div><div class="panel-title">餐段 × 时段收入热力图</div><div class="panel-caption">悬停查看收入、订单、折扣率</div></div>
            </div>
            <div class="chart" id="heatmapChart"></div>
          </div>
          <div class="panel">
            <div class="panel-head">
              <div><div class="panel-title">Top 时段</div><div class="panel-caption">按订单营业收入排序</div></div>
            </div>
            <div class="chart" id="daypartBar"></div>
          </div>
        </div>
      </section>

      <section class="section" id="opportunities">
        <div class="section-head">
          <div>
            <div class="section-kicker">06 Opportunity Pool</div>
            <h2>机会池：先用数据找抓手，再用业务访谈验证根因</h2>
          </div>
          <p class="section-note">按各项测算假设比较改善方向，优先选择影响较大、容易验证的一项开展试点。</p>
        </div>
        <div class="matrix" id="opportunityGrid"></div>
        <div class="callout" style="margin-top:18px;">
          各项情景可能涉及同一批订单或门店，建议分别试点、分别复盘，按实际效果决定下一轮扩展方向。
        </div>
      </section>

      <footer class="footer">
        <span>生成：__GENERATED_DATE__</span>
        <span>口径：订单营业收入；缺失指标不作为零值。</span>
      </footer>
    </main>
  </div>

  <script type="application/json" id="report-data">__PAYLOAD__</script>
  <script>
    const data = JSON.parse(document.getElementById('report-data').textContent);
    const COLORS = ['#006d77', '#355c9f', '#d96b3b', '#3a7d44', '#b85c00', '#7757a6', '#83c5be', '#b23a48'];
    const tooltip = document.getElementById('tooltip');

    const known = v => v !== null && v !== undefined && v !== '' && Number.isFinite(Number(v));
    const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
    const fmt = {
      wan: v => !known(v) ? '暂无数据' : `${(Number(v || 0) / 10000).toLocaleString('zh-CN', {maximumFractionDigits: 1})}万`,
      yuan: v => !known(v) ? '暂无数据' : `${Number(v || 0).toLocaleString('zh-CN', {maximumFractionDigits: 1})}元`,
      pct: v => !known(v) ? '暂无数据' : `${(Number(v || 0) * 100).toFixed(1)}%`,
      count: v => !known(v) ? '暂无数据' : Number(v || 0).toLocaleString('zh-CN', {maximumFractionDigits: 0}),
      plainWan: v => !known(v) ? '暂无数据' : `${Number(v || 0).toLocaleString('zh-CN', {maximumFractionDigits: 1})}万`
    };

    function showTip(event, html) {
      tooltip.innerHTML = html;
      tooltip.style.left = `${event.clientX}px`;
      tooltip.style.top = `${event.clientY}px`;
      tooltip.style.opacity = 1;
    }
    function hideTip() { tooltip.style.opacity = 0; }
    function svgEl(name, attrs = {}) {
      const el = document.createElementNS('http:' + '//www.w3.org/2000/svg', name);
      Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
      return el;
    }
    function clear(id) {
      const node = document.getElementById(id);
      node.innerHTML = '';
      return node;
    }
    function scale(value, min, max, outMin, outMax) {
      if (max === min) return (outMin + outMax) / 2;
      return outMin + (value - min) * (outMax - outMin) / (max - min);
    }
    function metricValue(row, metric) {
      return Number(row[metric] || 0);
    }

    function fillNumbers() {
      document.querySelectorAll('[data-format]').forEach(el => {
        const value = known(el.dataset.value) ? Number(el.dataset.value) : null;
        el.textContent = fmt[el.dataset.format](value);
      });
    }

    function renderInsights() {
      const grid = document.getElementById('insightGrid');
      grid.innerHTML = data.insights.map(item => `
        <article class="insight">
          <div class="insight-top">
            <span class="insight-label">${esc(item.label)}</span>
            <span class="insight-metric">${esc(item.metric)}</span>
          </div>
          <div class="insight-title">${esc(item.title)}</div>
          <div class="insight-note">${esc(item.note)}</div>
        </article>
      `).join('');
    }

    function renderMonthly(metric = 'net_revenue') {
      const host = clear('monthlyChart');
      const w = host.clientWidth || 620, h = 320, pad = {t: 18, r: 24, b: 44, l: 58};
      const rows = data.monthly;
      if (!rows.some(r => known(r[metric]))) return;
      const values = rows.filter(r => known(r[metric])).map(r => metricValue(r, metric));
      const max = Math.max(...values) * 1.1;
      const svg = svgEl('svg', {viewBox: `0 0 ${w} ${h}`, role: 'img'});
      const plotW = w - pad.l - pad.r, plotH = h - pad.t - pad.b;
      for (let i = 0; i <= 4; i++) {
        const y = pad.t + plotH * i / 4;
        svg.appendChild(svgEl('line', {x1: pad.l, y1: y, x2: w - pad.r, y2: y, stroke: '#d9e1e7'}));
      }
      const points = rows.map((r, i) => {
        const x = pad.l + plotW * i / Math.max(1, rows.length - 1);
        const y = known(r[metric]) ? pad.t + plotH - scale(metricValue(r, metric), 0, max, 0, plotH) : null;
        return [x, y, r];
      });
      if (metric !== 'discount_rate') {
        const barW = Math.max(10, plotW / rows.length * .52);
        points.forEach(([x, y, r], i) => {
          if (y === null) return;
          const val = metricValue(r, metric);
          const bh = scale(val, 0, max, 0, plotH);
          const rect = svgEl('rect', {x: x - barW / 2, y: pad.t + plotH - bh, width: barW, height: bh, rx: 4, fill: COLORS[i % COLORS.length], opacity: .82});
          rect.addEventListener('mousemove', e => showTip(e, `${esc(r['月'])}<br>${metric === 'net_revenue' ? '收入' : '订单'}：${metric === 'net_revenue' ? fmt.wan(val) : fmt.count(val)}`));
          rect.addEventListener('mouseleave', hideTip);
          svg.appendChild(rect);
        });
      } else {
        const validPoints = points.filter(p => p[1] !== null);
        const lineValues = validPoints.map(([, , row]) => Number(row.discount_rate));
        const minLineValue = Math.min(...lineValues), maxLineValue = Math.max(...lineValues);
        const hasDistinctExtremes = points.length > 1 && minLineValue !== maxLineValue;
        let segment = [];
        const flush = () => {
          if (segment.length) svg.appendChild(svgEl('polyline', {fill: 'none', stroke: '#c89b18', 'stroke-width': 3, points: segment.map(p => `${p[0]},${p[1]}`).join(' ')}));
          segment = [];
        };
        points.forEach(p => { if (p[1] === null) flush(); else segment.push(p); });
        flush();
        validPoints.forEach(([x, y, r]) => {
          const value = Number(r.discount_rate || 0);
          const isMin = hasDistinctExtremes && value === minLineValue;
          const isMax = hasDistinctExtremes && value === maxLineValue;
          const dot = svgEl('circle', {
            cx: x, cy: y, r: 5,
            fill: isMin ? '#e5484d' : isMax ? '#2f80ed' : '#f2c94c',
            stroke: isMin ? '#b42318' : isMax ? '#1c5fb8' : '#c89b18',
            'stroke-width': 2,
          });
          dot.addEventListener('mousemove', e => showTip(e, `${esc(r['月'])}<br>折扣率：${fmt.pct(r.discount_rate)}`));
          dot.addEventListener('mouseleave', hideTip);
          svg.appendChild(dot);
        });
      }
      rows.forEach((r, i) => {
        if (i % 2 === 0 || rows.length <= 8) {
          const x = pad.l + plotW * i / Math.max(1, rows.length - 1);
          const text = svgEl('text', {x, y: h - 16, 'text-anchor': 'middle', fill: '#627083', 'font-size': 11});
          text.textContent = String(r['月']).slice(5);
          svg.appendChild(text);
        }
      });
      host.appendChild(svg);
    }

    function renderMix() {
      const host = clear('mixChart');
      const legend = document.getElementById('mixLegend');
      const rows = [
        ['店内', data.overall.dine_in_revenue, COLORS[0]],
        ['外卖', data.overall.delivery_revenue, COLORS[2]],
        ['自提', data.overall.pickup_revenue, COLORS[4]],
      ].filter(r => Number(r[1]) > 0);
      const total = rows.reduce((a, r) => a + Number(r[1]), 0);
      const w = host.clientWidth || 460, h = 320, cx = w / 2, cy = 154, r = 104;
      const svg = svgEl('svg', {viewBox: `0 0 ${w} ${h}`});
      let angle = -Math.PI / 2;
      rows.forEach(([name, value, color]) => {
        const slice = Number(value) / total * Math.PI * 2;
        const end = angle + slice;
        const large = slice > Math.PI ? 1 : 0;
        const x1 = cx + r * Math.cos(angle), y1 = cy + r * Math.sin(angle);
        const x2 = cx + r * Math.cos(end), y2 = cy + r * Math.sin(end);
        const path = svgEl('path', {d: `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z`, fill: color});
        path.addEventListener('mousemove', e => showTip(e, `${esc(name)}<br>${fmt.wan(value)} / ${(value / total * 100).toFixed(1)}%`));
        path.addEventListener('mouseleave', hideTip);
        svg.appendChild(path);
        angle = end;
      });
      svg.appendChild(svgEl('circle', {cx, cy, r: 58, fill: '#fff'}));
      const center = svgEl('text', {x: cx, y: cy - 2, 'text-anchor': 'middle', 'font-size': 24, 'font-weight': 800, fill: '#18212f'});
      center.textContent = fmt.wan(total);
      svg.appendChild(center);
      const label = svgEl('text', {x: cx, y: cy + 20, 'text-anchor': 'middle', 'font-size': 12, fill: '#627083'});
      label.textContent = '订单营业收入';
      svg.appendChild(label);
      host.appendChild(svg);
      legend.innerHTML = rows.map(([name, value, color]) => `<span class="legend-item"><span class="swatch" style="background:${color}"></span>${esc(name)} ${(value / total * 100).toFixed(1)}%</span>`).join('');
    }

    function renderHorizontalBars(id, rows, metric, labelFn, options = {}) {
      const host = clear(id);
      rows = rows.filter(r => known(r[metric]));
      if (!rows.length) return;
      const w = host.clientWidth || 620, h = Math.max(300, rows.length * 34 + 56), pad = {t: 16, r: 44, b: 28, l: options.left || 110};
      const svg = svgEl('svg', {viewBox: `0 0 ${w} ${h}`});
      const values = rows.filter(r => known(r[metric])).map(r => metricValue(r, metric));
      const max = Math.max(...values) * 1.08;
      const plotW = w - pad.l - pad.r;
      rows.forEach((row, i) => {
        const y = pad.t + i * 32;
        const val = metricValue(row, metric);
        const bw = scale(val, 0, max, 0, plotW);
        const color = options.color || COLORS[i % COLORS.length];
        const label = svgEl('text', {x: pad.l - 10, y: y + 18, 'text-anchor': 'end', fill: '#18212f', 'font-size': 12});
        label.textContent = labelFn(row);
        svg.appendChild(label);
        const rect = svgEl('rect', {x: pad.l, y: y + 4, width: bw, height: 20, rx: 5, fill: color, opacity: .88});
        rect.addEventListener('mousemove', e => showTip(e, `${esc(labelFn(row))}<br>${options.tipLabel || metric}：${metric.includes('rate') || metric.includes('share') ? fmt.pct(val) : metric.includes('aov') ? fmt.yuan(val) : fmt.wan(val)}`));
        rect.addEventListener('mouseleave', hideTip);
        svg.appendChild(rect);
        const valueLabel = svgEl('text', {x: pad.l + bw + 8, y: y + 18, fill: '#627083', 'font-size': 12});
        valueLabel.textContent = metric.includes('rate') || metric.includes('share') ? fmt.pct(val) : metric.includes('aov') ? fmt.yuan(val) : fmt.wan(val);
        svg.appendChild(valueLabel);
      });
      host.appendChild(svg);
    }

    function renderStoreBar(metric = 'net_revenue') {
      const rows = [...selectedStores()].sort((a, b) => metricValue(b, metric) - metricValue(a, metric));
      const labels = {net_revenue: '收入', discount_rate: '折扣率', post_discount_aov: '折后单均'};
      renderHorizontalBars('storeBarChart', rows, metric, r => r.short_name, {tipLabel: labels[metric], left: 92, color: metric === 'discount_rate' ? '#d96b3b' : '#006d77'});
    }

    function renderScatter() {
      const host = clear('storeScatter');
      const w = host.clientWidth || 620, h = 320, pad = {t: 22, r: 30, b: 44, l: 58};
      const rows = selectedStores().filter(r => known(r.net_revenue) && known(r.post_discount_aov) && known(r.discount_rate));
      host.closest('.panel').hidden = !rows.length;
      if (!rows.length) return;
      const xs = rows.map(r => metricValue(r, 'post_discount_aov'));
      const ys = rows.map(r => metricValue(r, 'net_revenue'));
      const maxX = Math.max(...xs) * 1.1, minX = Math.min(...xs) * .92;
      const maxY = Math.max(...ys) * 1.08, minY = Math.min(...ys) * .88;
      const svg = svgEl('svg', {viewBox: `0 0 ${w} ${h}`});
      const plotW = w - pad.l - pad.r, plotH = h - pad.t - pad.b;
      svg.appendChild(svgEl('line', {x1: pad.l, y1: h - pad.b, x2: w - pad.r, y2: h - pad.b, stroke: '#d9e1e7'}));
      svg.appendChild(svgEl('line', {x1: pad.l, y1: pad.t, x2: pad.l, y2: h - pad.b, stroke: '#d9e1e7'}));
      rows.forEach((r, i) => {
        const x = scale(metricValue(r, 'post_discount_aov'), minX, maxX, pad.l, w - pad.r);
        const y = scale(metricValue(r, 'net_revenue'), minY, maxY, h - pad.b, pad.t);
        const radius = scale(metricValue(r, 'discount_rate'), 0.08, 0.15, 7, 18);
        const dot = svgEl('circle', {cx: x, cy: y, r: Math.max(7, radius), fill: COLORS[i % COLORS.length], opacity: .82});
        dot.addEventListener('mousemove', e => showTip(e, `${esc(r.short_name)}<br>收入：${fmt.wan(r.net_revenue)}<br>客单：${fmt.yuan(r.post_discount_aov)}<br>折扣：${fmt.pct(r.discount_rate)}`));
        dot.addEventListener('mouseleave', hideTip);
        svg.appendChild(dot);
        const text = svgEl('text', {x: x + 10, y: y + 4, fill: '#18212f', 'font-size': 11});
        text.textContent = r.short_name.slice(0, 4);
        svg.appendChild(text);
      });
      const xLabel = svgEl('text', {x: w / 2, y: h - 10, 'text-anchor': 'middle', fill: '#627083', 'font-size': 12});
      xLabel.textContent = '折后单均';
      svg.appendChild(xLabel);
      const yLabel = svgEl('text', {x: 14, y: 24, fill: '#627083', 'font-size': 12});
      yLabel.textContent = '收入';
      svg.appendChild(yLabel);
      host.appendChild(svg);
    }

    function renderSegments() {
      const order = ['明星店', '稳定现金流', '结构机会店', '低效待改善', '数据不足'];
      const grid = document.getElementById('segmentGrid');
      grid.innerHTML = order.map(name => {
        const count = selectedStores().filter(s => s.segment === name).length;
        const stores = selectedStores().filter(s => s.segment === name).map(s => s.short_name).join('、') || '暂无';
        return `<div class="segment"><span class="tile-label">${esc(name)}</span><b>${count} 家</b><div class="tile-foot">${esc(stores)}</div></div>`;
      }).join('');
    }

    const storeSizeSelect = document.getElementById('storeSizeSelect');
    [...new Set(data.stores.map(r => r.store_size))].forEach(size => {
      const option = document.createElement('option'); option.value = size; option.textContent = size; storeSizeSelect.appendChild(option);
    });
    function selectedStores() { return data.stores.filter(r => r.store_size === storeSizeSelect.value); }
    function updateStoreControls() {
      document.querySelectorAll('[data-store-metric]').forEach(btn => {
        btn.disabled = !selectedStores().some(r => known(r[btn.dataset.storeMetric]));
        btn.classList.toggle('active', btn.dataset.storeMetric === 'net_revenue');
      });
    }
    updateStoreControls();
    storeSizeSelect.addEventListener('change', () => { updateStoreControls(); renderStoreBar(); renderScatter(); renderSegments(); renderStoreTable(); });
    let storeSort = {key: 'net_revenue', dir: -1};
    function renderStoreTable() {
      const tbody = document.querySelector('#storeTable tbody');
      const rows = [...selectedStores()].sort((a, b) => {
        const av = a[storeSort.key], bv = b[storeSort.key];
        if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * storeSort.dir;
        return String(av).localeCompare(String(bv), 'zh-CN') * storeSort.dir;
      });
      tbody.innerHTML = rows.map(r => `
        <tr>
          <td>${esc(r.short_name)}</td>
          <td><span class="tag">${esc(r.segment)}</span></td>
          <td>${fmt.wan(r.net_revenue)}</td>
          <td>${fmt.pct(r.discount_rate)}</td>
          <td>${fmt.yuan(r.post_discount_aov)}</td>
          <td>${fmt.pct(r.delivery_revenue_share)}</td>
          <td>${fmt.pct(r.member_revenue_share)}</td>
          <td>${esc(r.action)}</td>
        </tr>
      `).join('');
    }

    function renderChannelChart() {
      const rows = [...data.channels].filter(r => known(r.net_revenue)).sort((a, b) => metricValue(b, 'net_revenue') - metricValue(a, 'net_revenue'));
      const host = clear('channelChart');
      if (!rows.length) return;
      const w = host.clientWidth || 620, h = Math.max(320, rows.length * 36 + 56), pad = {t: 16, r: 58, b: 28, l: 128};
      const svg = svgEl('svg', {viewBox: `0 0 ${w} ${h}`});
      const max = Math.max(...rows.map(r => metricValue(r, 'net_revenue'))) * 1.08;
      const plotW = w - pad.l - pad.r;
      rows.forEach((row, i) => {
        const y = pad.t + i * 34;
        const labelText = `${row['订单分类']}/${row['订单来源']}`;
        const label = svgEl('text', {x: pad.l - 10, y: y + 18, 'text-anchor': 'end', fill: '#18212f', 'font-size': 11});
        label.textContent = labelText.length > 12 ? labelText.slice(0, 12) : labelText;
        svg.appendChild(label);
        const bw = scale(metricValue(row, 'net_revenue'), 0, max, 0, plotW);
        const rect = svgEl('rect', {x: pad.l, y: y + 4, width: bw, height: 20, rx: 5, fill: COLORS[i % COLORS.length], opacity: .86});
        rect.addEventListener('mousemove', e => showTip(e, `${esc(labelText)}<br>收入：${fmt.wan(row.net_revenue)}<br>折扣：${fmt.pct(row.discount_rate)}<br>客单：${fmt.yuan(row.post_discount_aov)}`));
        rect.addEventListener('mouseleave', hideTip);
        svg.appendChild(rect);
        const dotX = pad.l + scale(metricValue(row, 'discount_rate'), 0, .36, 0, plotW);
        if (known(row.discount_rate)) svg.appendChild(svgEl('circle', {cx: dotX, cy: y + 14, r: 5, fill: '#d96b3b', stroke: '#fff', 'stroke-width': 2}));
      });
      host.appendChild(svg);
    }

    function renderMemberChart() {
      const rows = data.members;
      renderHorizontalBars('memberChart', rows, 'net_revenue', r => r['会员类型'], {tipLabel: '收入', left: 80, color: '#355c9f'});
    }

    function renderHeatmap() {
      const host = clear('heatmapChart');
      host.style.overflowX = 'auto';
      host.style.overflowY = 'hidden';
      host.style.paddingBottom = '4px';
      const rows = data.dayparts.filter(r => r['餐段'] && r['时段'] && known(r.net_revenue));
      if (!rows.length) return;
      const dayparts = [...new Set(rows.map(r => r['餐段']))];
      const times = [...new Set(rows.map(r => r['时段']))].sort();
      const map = new Map(rows.map(r => [`${r['餐段']}|${r['时段']}`, r]));
      const containerW = host.clientWidth || 640;
      const labelW = containerW < 520 ? 76 : 88;
      const minCellW = containerW < 520 ? 18 : 20;
      const rightPad = 12;
      const fittedCellW = (containerW - labelW - rightPad) / Math.max(1, times.length);
      const cellW = Math.max(minCellW, fittedCellW);
      const w = Math.max(containerW, labelW + times.length * cellW + rightPad);
      const cellH = 32;
      const h = 54 + dayparts.length * cellH;
      const max = Math.max(...rows.map(r => metricValue(r, 'net_revenue')));
      const svg = svgEl('svg', {viewBox: `0 0 ${w} ${h}`});
      svg.style.width = `${w}px`;
      svg.style.height = `${h}px`;
      times.forEach((t, i) => {
        const text = svgEl('text', {x: labelW + i * cellW + cellW / 2, y: 22, 'text-anchor': 'middle', fill: '#627083', 'font-size': 10});
        text.textContent = t.slice(0, 2);
        svg.appendChild(text);
      });
      dayparts.forEach((d, yIdx) => {
        const label = svgEl('text', {x: labelW - 8, y: 48 + yIdx * cellH, 'text-anchor': 'end', fill: '#18212f', 'font-size': 12});
        label.textContent = d.trim() || '未设置';
        svg.appendChild(label);
        times.forEach((t, xIdx) => {
          const row = map.get(`${d}|${t}`);
          const val = row ? metricValue(row, 'net_revenue') : null;
          const alpha = val ? scale(val, 0, max, .15, 1) : .04;
          const rect = svgEl('rect', {x: labelW + xIdx * cellW, y: 30 + yIdx * cellH, width: Math.max(4, cellW - 3), height: cellH - 4, rx: 4, fill: '#006d77', opacity: alpha});
          rect.addEventListener('mousemove', e => showTip(e, `${esc(d)} ${esc(t)}<br>收入：${fmt.wan(val)}<br>订单：${fmt.count(row ? row.positive_orders : null)}<br>折扣：${fmt.pct(row ? row.discount_rate : null)}`));
          rect.addEventListener('mouseleave', hideTip);
          svg.appendChild(rect);
        });
      });
      host.appendChild(svg);
    }

    function renderDaypartBar() {
      const rows = [...data.dayparts].sort((a, b) => metricValue(b, 'net_revenue') - metricValue(a, 'net_revenue')).slice(0, 12);
      renderHorizontalBars('daypartBar', rows, 'net_revenue', r => `${r['餐段']} ${r['时段']}`, {left: 128, color: '#3a7d44'});
    }

    function renderOpportunities() {
      const grid = document.getElementById('opportunityGrid');
      grid.innerHTML = data.opportunities.map((o, i) => `
        <article class="opportunity">
          <span class="tile-label">${esc(o.name)}</span>
          <div class="value">${Number(o.value).toLocaleString('zh-CN', {maximumFractionDigits: 1})}${esc(o.unit)}</div>
          <div class="logic">${esc(o.logic)}</div>
          <div class="legend">
            <span class="legend-item"><span class="swatch" style="background:${COLORS[i]}"></span>置信度 ${esc(o.confidence)}</span>
            <span class="legend-item">执行 ${esc(o.effort)}</span>
          </div>
          <div class="owner">责任方向：${esc(o.owner)}</div>
        </article>
      `).join('');
    }

    function bindControls() {
      document.querySelectorAll('[data-month-metric]').forEach(btn => {
        btn.addEventListener('click', () => {
          document.querySelectorAll('[data-month-metric]').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          renderMonthly(btn.dataset.monthMetric);
        });
      });
      document.querySelectorAll('[data-store-metric]').forEach(btn => {
        btn.addEventListener('click', () => {
          document.querySelectorAll('[data-store-metric]').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          renderStoreBar(btn.dataset.storeMetric);
        });
      });
      document.querySelectorAll('#storeTable th[data-sort]').forEach(th => {
        th.addEventListener('click', () => {
          const key = th.dataset.sort;
          storeSort.dir = storeSort.key === key ? storeSort.dir * -1 : -1;
          storeSort.key = key;
          renderStoreTable();
        });
      });
      window.addEventListener('resize', () => {
        renderMonthly(document.querySelector('[data-month-metric].active').dataset.monthMetric);
        renderMix();
        renderStoreBar(document.querySelector('[data-store-metric].active').dataset.storeMetric);
        renderScatter();
        renderChannelChart();
        renderMemberChart();
        renderHeatmap();
        renderDaypartBar();
      });
    }

    function applyAvailability() {
      const hide = id => { document.getElementById(id).hidden = true; const link = document.querySelector(`.nav a[href="#${id}"]`); if (link) link.hidden = true; };
      Object.entries(data.availability).forEach(([id, enabled]) => { if (id !== 'current' && !enabled) hide(id); });
      if (!data.availability.current) document.querySelector('.score-panel').hidden = true;
      const panels = {monthlyChart: data.monthly.some(r => known(r.net_revenue)),
        mixChart: ['dine_in_revenue', 'delivery_revenue', 'pickup_revenue'].every(k => known(data.overall[k])),
        channelChart: data.channels.some(r => known(r.net_revenue)), memberChart: data.members.some(r => known(r.net_revenue))};
      Object.entries(panels).forEach(([id, enabled]) => { if (!enabled) document.getElementById(id).closest('.panel').hidden = true; });
      document.querySelectorAll('[data-format]').forEach(el => { if (!known(el.dataset.value)) { const tile = el.closest('.tile, .score-mini'); if (tile) tile.hidden = true; } });
      document.querySelectorAll('[data-month-metric]').forEach(btn => { btn.disabled = !data.monthly.some(r => known(r[btn.dataset.monthMetric])); });
    }
    applyAvailability();
    fillNumbers();
    renderInsights();
    renderMonthly();
    renderMix();
    renderStoreBar();
    renderScatter();
    renderSegments();
    renderStoreTable();
    renderChannelChart();
    renderMemberChart();
    renderHeatmap();
    renderDaypartBar();
    renderOpportunities();
    bindControls();
  </script>
</body>
</html>
'''
