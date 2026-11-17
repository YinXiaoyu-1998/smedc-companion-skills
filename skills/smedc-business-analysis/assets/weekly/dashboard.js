(() => {
  'use strict';
  const D = JSON.parse(document.getElementById('report-data').textContent);
  const content = JSON.parse(document.getElementById('weekly-dashboard-content').textContent);
  const X = content.details;
  const V = content.customer_voice;
  const company = D.meta.company;
  const windowDates = D.meta.target_windows;
  const fullDate = (value) => value.replaceAll('-', '.');
  const shortDate = (value) => fullDate(value).slice(5);
  const dateRange = (period, year = false) => {
    const { start, end } = windowDates[period];
    return (
      (year ? fullDate(start) : shortDate(start)) +
      ' — ' +
      (year && start.slice(0, 4) !== end.slice(0, 4) ? fullDate(end) : shortDate(end))
    );
  };
  const STRUCTURE = JSON.parse(document.getElementById('report-structure').textContent);
  function resolveRoute(parts) {
    return STRUCTURE.routes.find((r) => {
      const p = r.pattern.split('/');
      return (
        p.length === parts.length &&
        p.every((v, i) => (v.startsWith(':') ? Boolean(parts[i]) : v === parts[i]))
      );
    });
  }
  const rows = D.comparison.filter((row) => row.current_rows);
  const original = document.querySelector('body>main');
  const app = document.createElement('div');
  app.id = 'px-app';
  document.body.insertBefore(app, original);
  const esc = (v) =>
    String(v ?? '').replace(
      /[&<>"']/g,
      (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
    );
  const num = (v, d = 2) =>
    v === null || v === undefined || !Number.isFinite(Number(v))
      ? '—'
      : Number(v).toLocaleString('zh-CN', { maximumFractionDigits: d, minimumFractionDigits: d });
  const wan = (v) => (v === null || v === undefined ? '—' : num(Number(v) / 10000, 2) + ' 万');
  const pct = (v) => (v === null || v === undefined ? '—' : (v >= 0 ? '+' : '') + num(v * 100, 1) + '%');
  const short = (s) => s.match(/[（(]([^）()]+)[）)]$/)?.[1] || s;
  const route = (...xs) => {
    if (!resolveRoute(xs.map(String))) throw Error('Unregistered report route');
    return '#/alpha/' + xs.map((x) => encodeURIComponent(x)).join('/');
  };
  const link = (path, title, desc = '', icon = '↗') =>
    `<a class="px-module" href="${path}"><span class="px-icon" aria-hidden="true">${icon}</span><h3>${esc(title)}</h3><p>${esc(desc)}</p><span class="px-link">进入查看 →</span></a>`;
  const detail = (title, html) =>
    `<details class="px-detail"><summary>${esc(title)}</summary><div class="px-detail-body">${html}</div></details>`;
  const table = (heads, rs) =>
    `<div class="px-data-cards" role="list" aria-label="${esc(heads.join('、'))}">${rs
      .map((r) => {
        let delta = '';
        if (heads.length === 3 && heads[1] === '本周' && heads[2] === '上周') {
          const raw = r.slice(1).map((x) => String(x).replace(/,/g, ''));
          if (raw.every((x) => /^-?\d+(\.\d+)?$/.test(x))) {
            const current = Number(raw[0]),
              previous = Number(raw[1]),
              change = current - previous;
            delta = `<p class="px-card-delta">较上周 ${change > 0 ? '+' : ''}${num(change, Number.isInteger(current) && Number.isInteger(previous) ? 0 : 2)}${previous !== 0 ? '（' + pct(change / Math.abs(previous)) + '）' : ''}</p>`;
          }
        }
        return `<article class="px-fact-card" role="listitem"><h3>${r[0]}</h3><dl>${r
          .slice(1)
          .map((c, i) => `<div><dt>${esc(heads[i + 1])}</dt><dd>${c}</dd></div>`)
          .join('')}</dl>${delta}</article>`;
      })
      .join('')}</div>`;

  const kpis = (items) =>
    `<div class="px-kpis">${items.map((x) => `<div class="px-kpi"><label>${esc(x[0])}</label><strong>${esc(x[1])}</strong><small>${esc(x[2] || '')}</small></div>`).join('')}</div>`;
  const summary = (text, label = '本周判断') =>
    `<div class="px-summary"><label>${esc(label)}</label><p>${esc(text)}</p></div>`;
  const heading = (title, sub = '', eyebrow = 'WEEKLY REVIEW') =>
    `<div class="px-headline"><div><div class="px-kicker">${esc(eyebrow)}</div><h1 tabindex="-1">${esc(title)}</h1><p>${esc(sub)}</p></div></div>`;
  const reviews = new Map(
    [...document.querySelectorAll('.store-review-card')].map((n) => [
      n.querySelector('summary').textContent.trim(),
      n,
    ]),
  );
  const advice = [...document.querySelectorAll('#business-advisory>details')];
  const ptext = (node, i) =>
    node?.querySelectorAll(':scope>p')[i]?.textContent.replace(/^[^：]+：/, '') || '';
  const mealNode = (name) => reviews.get(name)?.querySelector('[data-review-section="meal_periods"]');
  const crumbs = (items) =>
    `<nav class="px-breadcrumbs" aria-label="阅读路径"><a href="${route('home')}">周报总览</a>${items.map((x) => `<span aria-hidden="true">/</span>${x[1] ? `<a href="${x[1]}">${esc(x[0])}</a>` : `<span aria-current="page">${esc(x[0])}</span>`}`).join('')}</nav>`;
  const storeCrumbs = (i, ...extra) =>
    crumbs([[short(rows[i]['门店名称']), extra.length ? route('store', i) : null], ...extra]);
  let mounted = [];
  let lastRoute = '';
  const saved = new Map();
  const listStates = new Map();
  let storeQuery = '',
    storeGroup = '全部';
  function restore() {
    if (dashboardTrendObserver) {
      dashboardTrendObserver.disconnect();
      dashboardTrendObserver = null;
    }
    document.querySelectorAll('#trend text[data-full-date]').forEach((t) => {
      t.textContent = t.dataset.fullDate;
      delete t.dataset.fullDate;
    });
    if (dashboardObserver) {
      dashboardObserver.disconnect();
      dashboardObserver = null;
    }
    if (app.dataset.page === 'home') {
      dashboardTrendStore = document.getElementById('trendStoreSelect')?.value || '__all__';
    }
    for (const { node, mark } of mounted) {
      mark.before(node);
      mark.remove();
    }
    mounted = [];
    original.classList.remove('px-full');
  }
  function mount(node, target = 'px-mount') {
    const mark = document.createComment('panel-position');
    node.before(mark);
    mounted.push({ node, mark });
    document.getElementById(target).append(node);
    convertLegacyTables(node);
  }
  function convertLegacyTables(root) {
    for (const t of root.querySelectorAll('table')) {
      t.classList.add('px-source-table');
      let out = t.nextElementSibling;
      if (!out?.classList.contains('px-legacy-cards')) {
        out = document.createElement('div');
        out.className = 'px-legacy-cards';
        t.after(out);
      }
      const heads = [...t.querySelectorAll('thead th')].map((x) => x.textContent.trim());
      const body = [...t.querySelectorAll('tbody tr')]
        .map((tr) => [...tr.querySelectorAll(':scope>td')].map((td) => esc(td.textContent.trim())))
        .filter((r) => r.length);
      if (heads.length && body.length) out.innerHTML = table(heads, body);
      else {
        t.classList.remove('px-source-table');
        out.remove();
      }
    }
  }
  const charts = [];
  for (const id of ['summary', 'ranking', 'stores', 'channels', 'drivers', 'daypart-drivers', 'dayparts']) {
    const sec = document.getElementById(id);
    if (!sec) continue;
    const panels = [...sec.querySelectorAll(':scope>.panel,:scope>.grid-2>.panel')];
    if (panels.length)
      for (const node of panels)
        charts.push({
          section: id,
          title: node.querySelector('h3')?.textContent || sec.querySelector('h2')?.textContent,
          node,
        });
    else charts.push({ section: id, title: sec.querySelector('h2')?.textContent, node: sec });
  }
  const trendNode = document.getElementById('trend').closest('.panel');
  const hourlyNode = document.getElementById('hourlyRevenueBar').closest('.panel');
  const mobileNavQuery = matchMedia('(max-width: 820px)');
  let sidebarCollapsed = false;
  let mobileNavOpen = false;
  let activeRouteId = 'home';
  const sidebarLinks = [
    ['总览', ['home'], '▦'],
    ['门店', ['allstores'], '▤'],
    ['经营建议', ['priorities'], '✓'],
    ['顾客声音', ['reviews', 'all'], '◉'],
    ['跨店专题', ['topics'], '▥'],
  ];

  function sidebarActivePage(page) {
    if (['review_topic', 'review_evidence', 'reviews_store', 'reviews_all'].includes(page)) return 'reviews';
    if (['priorities', 'advice', 'advice_detail'].includes(page)) return 'priorities';
    if (['topics', 'chart', 'benchmark', 'trends'].includes(page)) return 'topics';
    return page === 'home' ? 'home' : 'allstores';
  }

  function syncSidebar() {
    const mobile = mobileNavQuery.matches;
    const collapsed = !mobile && sidebarCollapsed;
    const open = mobile && mobileNavOpen;
    document.body.classList.toggle('px-sidebar-collapsed', collapsed);
    document.body.classList.toggle('px-sidebar-open', open);
    const navigation = document.getElementById('px-sidebar-nav');
    navigation.inert = mobile && !open;
    navigation.querySelector('button').setAttribute('aria-expanded', String(mobile ? open : !collapsed));
    document.getElementById('px-mobile-open').setAttribute('aria-expanded', String(open));
  }

  function setMobileNav(open, returnFocus = false) {
    mobileNavOpen = open;
    syncSidebar();
    if (open) document.getElementById('px-sidebar-toggle').focus();
    else if (returnFocus) document.getElementById('px-mobile-open').focus();
  }

  mobileNavQuery.addEventListener('change', () => {
    mobileNavOpen = false;
    syncSidebar();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && mobileNavOpen) setMobileNav(false, true);
  });

  function shell(body) {
    const current = sidebarActivePage(activeRouteId);
    app.innerHTML = `
  <aside id="px-sidebar-nav" class="px-sidebar" aria-label="周报导航">
   <div class="px-sidebar-head">
    <a class="px-sidebar-brand" href="${route('home')}" aria-label="${esc(company)}经营周报"><span class="px-sidebar-logo" aria-hidden="true">${esc(company.slice(0, 1))}</span><span class="px-sidebar-text">${esc(company)}</span></a>
    <button id="px-sidebar-toggle" type="button" aria-controls="px-sidebar-links" aria-label="收起或展开侧栏" title="收起或展开侧栏"><span aria-hidden="true">☰</span></button>
   </div>
   <nav id="px-sidebar-links" aria-label="主导航">
    ${sidebarLinks.map(([label, path, icon]) => `<a href="${route(...path)}" aria-label="${label}" title="${label}" ${current === path[0] ? 'aria-current="page"' : ''}><span class="px-sidebar-icon" aria-hidden="true">${icon}</span><span class="px-sidebar-text">${label}</span></a>`).join('')}
   </nav>
  </aside>
  <button class="px-sidebar-scrim" type="button" aria-label="关闭导航" tabindex="-1"></button>
  <header class="px-mobile-header">
   <button id="px-mobile-open" type="button" aria-label="打开导航" aria-controls="px-sidebar-nav"><span aria-hidden="true">☰</span></button>
   <a href="${route('home')}">${esc(company)}经营周报</a>
  </header>
  ${body}
  <footer class="px-footer"><span>${esc(dateRange('current', true))} · 订单营业收入</span><span><a href="${route('design')}">数据说明</a> · <a href="${route('original')}">原版完整报告</a></span></footer>`;
    document.body.classList.add('px-has-sidebar');
    mobileNavOpen = false;
    syncSidebar();
    document.getElementById('px-sidebar-toggle').onclick = () => {
      if (mobileNavQuery.matches) setMobileNav(false, true);
      else {
        sidebarCollapsed = !sidebarCollapsed;
        syncSidebar();
      }
    };
    document.getElementById('px-mobile-open').onclick = () => setMobileNav(!mobileNavOpen, mobileNavOpen);
    app.querySelector('.px-sidebar-scrim').onclick = () => setMobileNav(false, true);
    app.querySelectorAll('.px-sidebar a').forEach((link) => {
      link.addEventListener('click', () => {
        if (!mobileNavOpen) return;
        const samePage = link.hash === location.hash;
        setMobileNav(false, samePage);
      });
    });
  }
  function priorityCards() {
    return `<div class="px-priorities">${advice
      .map((a, j) => {
        const parts = a.querySelector('summary').textContent.split(' · ');
        return `<a href="${route('advice', j)}" class="px-priority"><span class="px-muted">${esc(parts.slice(0, 2).join(' · '))}</span><span class="px-arrow">↗</span><h3>${esc(parts.slice(2).join(' · '))}</h3><small>判断 · 行动 · 证据</small></a>`;
      })
      .join('')}</div>`;
  }
  function cards() {
    return (
      rows
        .map((r, i) => ({ r, i }))
        .filter(
          ({ r }) =>
            (storeGroup === '全部' || r.store_size_bucket === storeGroup) &&
            r['门店名称'].includes(storeQuery),
        )
        .map(
          ({ r, i }) =>
            `<a class="px-store" href="${route('store', i)}"><div class="px-store-top"><h3>${esc(r['门店名称'])}</h3><span class="px-chip">${esc(r.store_size_bucket)}</span></div><div class="px-store-revenue"><strong>${wan(r.current_net_revenue)}</strong><span class="${r.wow_net_revenue_pct < 0 ? 'px-down' : 'px-up'}">环比 ${pct(r.wow_net_revenue_pct)}</span></div><p>${esc(ptext(mealNode(r['门店名称']), 1).split('。')[0])}。</p><div class="px-store-foot"><span>餐段 · 菜品 · 订单 · 评价</span><span>进入门店 →</span></div></a>`,
        )
        .join('') || '<p class="px-empty">未找到匹配门店</p>'
    );
  }
  function storeGrid() {
    return `<section class="px-section"><div class="px-section-head"><div><h2>从一家门店开始</h2><p>${rows.length} 家门店 · 先看概况，再选要深入的经营问题</p></div><div class="px-tools"><input aria-label="搜索门店" placeholder="搜索门店" value="${esc(storeQuery)}">${['全部', ...new Set(rows.map((row) => row.store_size_bucket))].map((g) => `<button data-group="${g}" aria-pressed="${storeGroup === g}">${g}</button>`).join('')}</div></div><div class="px-stores" id="px-stores">${cards()}</div></section>`;
  }
  function bindSearch() {
    const input = app.querySelector('input[aria-label="搜索门店"]');
    if (input)
      input.addEventListener('input', () => {
        storeQuery = input.value;
        document.getElementById('px-stores').innerHTML = cards();
      });
    app.querySelectorAll('[data-group]').forEach(
      (b) =>
        (b.onclick = () => {
          storeGroup = b.dataset.group;
          app
            .querySelectorAll('[data-group]')
            .forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
          document.getElementById('px-stores').innerHTML = cards();
        }),
    );
  }
  function topics() {
    return `<div class="px-modules">${link(route('benchmark'), '门店横向对比', '按大小店看规模、增长和变化贡献', '▥')}${link(route('trends'), '收入趋势', '企业与单店，保留 52 周时间探索', '⌁')}${link(route('reviews', 'all'), '顾客声音', '逐店核心判断 → 值得保持与优先核查 → 引用证据', '◎')}</div>`;
  }
  let dashboardObserver = null;
  let dashboardTrendObserver = null;
  let dashboardHour = '__all__';
  let dashboardTrendStore = '__all__';
  const palette = {
    teal: '#087f86',
    blue: '#426eb1',
    gold: '#c39934',
    green: '#578867',
    orange: '#be7250',
    purple: '#8770ac',
    red: '#b85c56',
    ink: '#29423c',
    muted: '#708077',
    line: '#e8ede7',
  };
  const revenueLegend = [
    ['堂食', palette.teal],
    ['外卖', palette.blue],
    ['其他', palette.gold],
  ];
  const svgText = (x, y, text, extra = '') => `<text x="${x}" y="${y}" ${extra}>${esc(text)}</text>`;
  const svgRoot = (w, h, title, body) =>
    `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(title)}"><title>${esc(title)}</title>${body}</svg>`;
  const chartLink = (i, title, body) =>
    `<a href="${route('store', i)}" aria-label="${esc(title)}"><title>${esc(title)}</title>${body}</a>`;
  const dashSum = (field) =>
    rows.every((r) => Number.isFinite(r[field])) ? rows.reduce((s, r) => s + r[field], 0) : null;
  const deltaRatio = (c, p) => (c !== null && p !== null && p !== 0 ? (c - p) / Math.abs(p) : null);
  function readableTrendTicks() {
    const small = innerWidth <= 720;
    document.querySelectorAll('#dash-trend-host #trend svg text').forEach((t) => {
      const full = t.dataset.fullDate || t.textContent;
      if (/^\d{4}-\d{2}-\d{2}$/.test(full)) {
        t.dataset.fullDate = full;
        t.setAttribute('aria-label', full);
        const label = small ? full.slice(5).replace('-', '/') : full;
        if (t.textContent !== label) t.textContent = label;
      }
    });
  }
  function dashboardRank(width) {
    const left = 86;
    const right = 53;
    const rowHeight = 23;
    const barHeight = 13;
    const plotWidth = width - left - right;
    const maximum = Math.max(1, ...rows.map((row) => row.current_net_revenue));
    let body = '';
    let y = 22;

    for (const group of D.segment_groups) {
      body += svgText(3, y - 7, group.label, 'class="dash-group-label"');
      body += svgText(
        width - 3,
        y - 7,
        `中位数 ${num(group.revenue_threshold / 10000, 1)}万`,
        'text-anchor="end" class="dash-small"',
      );
      const stores = rows
        .map((row, index) => ({ row, index }))
        .filter(({ row }) => row.store_size_bucket === group.key)
        .sort((a, b) => b.row.current_net_revenue - a.row.current_net_revenue);

      for (const { row, index } of stores) {
        const total = row.current_net_revenue;
        const dineIn = row.current_dine_in_revenue;
        const delivery = row.current_delivery_revenue;
        const other = total - dineIn - delivery;
        let x = left;
        let mark = svgText(left - 8, y + 12, short(row['门店名称']), 'text-anchor="end"');
        for (const [label, value, color] of [
          ['堂食', dineIn, palette.teal],
          ['外卖', delivery, palette.blue],
          ['其他', other, palette.gold],
        ]) {
          if (!Number.isFinite(value) || value < 0.01) continue;
          const barWidth = (plotWidth * value) / maximum;
          mark += `<rect x="${x}" y="${y + 1}" width="${barWidth}" height="${barHeight}" fill="${color}"><title>${label} ${num(value)} 元</title></rect>`;
          x += barWidth;
        }
        mark += svgText(x + 5, y + 12, num(total / 10000, 1) + '万', 'class="dash-value"');
        body += chartLink(
          index,
          `${row['门店名称']}，总收入 ${num(total)} 元，堂食 ${num(dineIn)} 元，外卖 ${num(delivery)} 元`,
          mark,
        );
        y += rowHeight;
      }
      y += 24;
    }
    return svgRoot(width, y - 18, '门店收入排名及堂食／外卖结构，按大小店分组', body);
  }

  function dashboardGrowth(width) {
    const sorted = rows
      .map((row, index) => ({ row, index }))
      .sort((a, b) => b.row.wow_net_revenue_pct - a.row.wow_net_revenue_pct);
    const nameX = 76;
    const left = 124;
    const right = 48;
    const top = 7;
    const rowHeight = 26;
    const height = top + rowHeight * rows.length + 3;
    const plotWidth = width - left - right;
    const series = [
      ['wow_net_revenue_pct', 0, palette.teal],
      ['yoy_net_revenue_pct', 11, palette.blue],
    ];
    const values = rows.flatMap((row) => series.map(([key]) => row[key])).filter(Number.isFinite);
    const min = Math.min(-0.35, ...values);
    const max = Math.max(0.35, ...values);
    const scale = (number) => left + ((number - min) / (max - min)) * plotWidth;
    const zero = scale(0);
    let body = `<line x1="${zero}" x2="${zero}" y1="2" y2="${height - 4}" stroke="#bdc9c0"/>`;

    for (const [position, { row, index }] of sorted.entries()) {
      const y = top + position * rowHeight;
      let mark = svgText(nameX, y + 12, short(row['门店名称']), 'text-anchor="end"');
      for (const [key, offset, color] of series) {
        const value = row[key];
        if (!Number.isFinite(value)) {
          mark += svgText(zero + 5, y + offset + 8, '—', 'class="dash-small"');
          continue;
        }
        const end = scale(value);
        mark += `<rect x="${Math.min(zero, end)}" y="${y + offset}" width="${Math.max(Math.abs(end - zero), 0.8)}" height="7" rx="2" fill="${color}"/>`;
        mark += svgText(
          end + (value >= 0 ? 5 : -5),
          y + offset + 7,
          pct(value),
          `text-anchor="${value >= 0 ? 'start' : 'end'}" class="dash-growth-value"`,
        );
      }
      body += chartLink(
        index,
        `${row['门店名称']}，环比 ${pct(row.wow_net_revenue_pct)}，同比 ${pct(row.yoy_net_revenue_pct)}`,
        mark,
      );
    }
    return svgRoot(width, height, '门店收入环比与同比，百分比标注于各条末端', body);
  }

  function dashboardQuadrants(w) {
    const h = D.segment_groups.length * 130 + 3,
      left = 32,
      right = 12,
      plotW = w - left - right;
    let body = '';
    D.segment_groups.forEach((group, g) => {
      const top = 20 + g * 130,
        plotH = 94;
      const selected = rows
        .map((r, i) => ({ r, i }))
        .filter((x) => x.r.store_size_bucket === group.key && Number.isFinite(x.r.wow_net_revenue_pct));
      const minX = Math.min(-0.32, ...selected.map((x) => x.r.wow_net_revenue_pct - 0.04)),
        maxX = Math.max(0.36, ...selected.map((x) => x.r.wow_net_revenue_pct + 0.04));
      const yMax =
        Math.ceil(
          Math.max(1, group.revenue_threshold, ...selected.map((x) => x.r.current_net_revenue)) / 50000,
        ) * 50000;
      const sx = (v) => left + ((v - minX) / (maxX - minX)) * plotW,
        sy = (v) => top + plotH - (v / yMax) * plotH,
        midY = sy(group.revenue_threshold),
        zero = sx(0);
      body +=
        svgText(4, top - 10, group.label, `class="dash-group-label"`) +
        svgText(
          w - 7,
          top - 10,
          `收入中位数 ${num(group.revenue_threshold / 10000, 1)}万`,
          `text-anchor="end" class="dash-small"`,
        );
      body += `<rect x="${zero}" y="${top}" width="${w - right - zero}" height="${midY - top}" fill="#f1f5ef"/><line x1="${left}" x2="${w - right}" y1="${midY}" y2="${midY}" stroke="#bacbbf" stroke-dasharray="3 3"/><line x1="${zero}" x2="${zero}" y1="${top}" y2="${top + plotH}" stroke="#bacbbf" stroke-dasharray="3 3"/><path d="M${left} ${top}V${top + plotH}H${w - right}" fill="none" stroke="#cbd5cc"/>`;
      body +=
        svgText(left + 4, top + 11, '高收入·回落', `class="dash-zone"`) +
        svgText(w - right - 4, top + 11, '高收入·增长', `text-anchor="end" class="dash-zone"`) +
        svgText(left + 4, top + plotH - 5, '低收入·回落', `class="dash-zone"`) +
        svgText(w - right - 4, top + plotH - 5, '低收入·增长', `text-anchor="end" class="dash-zone"`);
      const boxes = [];
      for (const { r, i } of selected.sort((a, b) => b.r.current_net_revenue - a.r.current_net_revenue)) {
        const x = sx(r.wow_net_revenue_pct),
          y = sy(r.current_net_revenue),
          label = short(r['门店名称']),
          tw = label.length * 11;
        let chosen = null;
        for (const [dx, dy] of [
          [8, -8],
          [8, 17],
          [-tw - 8, -8],
          [-tw - 8, 17],
          [8, -23],
          [-tw - 8, 32],
          [8, 32],
        ]) {
          const bx = Math.max(left + 2, Math.min(w - right - tw - 2, x + dx)),
            by = Math.max(top + 19, Math.min(top + plotH - 11, y + dy));
          const box = { x: bx, y: by - 10, w: tw, h: 14 };
          if (
            !boxes.some(
              (b) =>
                box.x < b.x + b.w + 3 &&
                box.x + box.w + 3 > b.x &&
                box.y < b.y + b.h + 3 &&
                box.y + box.h + 3 > b.y,
            )
          ) {
            chosen = box;
            break;
          }
        }
        chosen ??= {
          x: Math.max(left + 2, Math.min(w - right - tw - 2, x + 8)),
          y: Math.min(top + plotH - 20, y + 17) - 10,
          w: tw,
          h: 14,
        };
        boxes.push(chosen);
        const color =
          r.wow_net_revenue_pct < 0
            ? palette.red
            : r.current_net_revenue >= group.revenue_threshold
              ? palette.green
              : palette.blue;
        body += chartLink(
          i,
          `${r['门店名称']}，收入${wan(r.current_net_revenue)}，环比${pct(r.wow_net_revenue_pct)}`,
          `<line x1="${x}" y1="${y}" x2="${chosen.x + tw / 2}" y2="${chosen.y + 7}" stroke="${color}" opacity=".35"/><circle cx="${x}" cy="${y}" r="5" fill="${color}" stroke="white" stroke-width="1.5"/>` +
            svgText(chosen.x, chosen.y + 10, label, `class="dash-scatter-label"`),
        );
      }
      for (const v of [-0.25, 0, 0.25])
        body += svgText(
          sx(v),
          top + plotH + 14,
          (v * 100).toFixed(0) + '%',
          `text-anchor="middle" class="dash-small"`,
        );
    });
    return svgRoot(w, h, '门店经营四象限，横轴收入环比，纵轴订单营业收入，分别使用大小店组中位数', body);
  }
  function dashboardPlatforms(width) {
    const left = 86,
      right = 53,
      plotWidth = width - left - right,
      rowHeight = 23;
    const series = [
      ['美团', 'current_meituan_delivery_revenue', palette.green],
      ['淘宝闪购', 'current_eleme_delivery_revenue', palette.purple],
      ['京东', 'current_jd_delivery_revenue', palette.orange],
    ];
    const totals = rows.map((row) => series.reduce((sum, [, key]) => sum + (row[key] ?? 0), 0));
    const maximum = Math.max(1, ...totals);
    let body = '';
    rows.forEach((row, index) => {
      const y = 6 + index * rowHeight;
      let mark = svgText(left - 8, y + 12, short(row['门店名称']), 'text-anchor="end"');
      let x = left;
      for (const [label, key, color] of series) {
        const value = row[key];
        if (!Number.isFinite(value) || value <= 0) continue;
        const barWidth = (plotWidth * value) / maximum;
        mark += `<rect x="${x}" y="${y + 1}" width="${barWidth}" height="13" fill="${color}"><title>${label} ${num(value)} 元</title></rect>`;
        x += barWidth;
      }
      mark += svgText(x + 5, y + 12, num(totals[index] / 10000, 1) + '万', 'class="dash-value"');
      body += chartLink(index, `${row['门店名称']}，外卖平台收入合计 ${num(totals[index])} 元`, mark);
    });
    return svgRoot(width, rows.length * rowHeight + 9, '外卖平台收入', body);
  }
  function rankedRevenueDetail() {
    const title = STRUCTURE.dashboard.panels.find((panel) => panel.id === 'ranking').title;
    shell(`${crumbs([['跨店经营专题', route('benchmark')], [title]])}${heading(title)}
 <section class="dash-panel"><div class="dash-legend">${chartLegend(revenueLegend)}</div><div class="dash-plot" id="dash-ranked-detail"></div></section>`);
    const plot = document.getElementById('dash-ranked-detail');
    const draw = () => {
      plot.innerHTML = dashboardRank(Math.floor(plot.clientWidth));
    };
    draw();
    dashboardObserver = new ResizeObserver(draw);
    dashboardObserver.observe(plot);
  }

  function dashboardHours(w) {
    const entity =
      D.hourly_revenue_entities.find((e) => e.key === dashboardHour) || D.hourly_revenue_entities[0];
    const rs = entity.rows,
      left = 45,
      right = 12,
      top = 18,
      bottom = 33,
      h = 220,
      plotH = h - top - bottom,
      span = w - left - right,
      max = Math.ceil(Math.max(...rs.map((r) => r.net_revenue)) / 50000) * 50000;
    let body = '';
    for (let i = 0; i <= 4; i++) {
      const val = (max * i) / 4,
        y = top + plotH - (val / max) * plotH;
      body +=
        `<line x1="${left}" x2="${w - right}" y1="${y}" y2="${y}" stroke="${palette.line}"/>` +
        svgText(left - 7, y + 4, num(val / 10000, 1), `text-anchor="end" class="dash-small"`);
    }
    rs.forEach((r, i) => {
      const x = left + (i * span) / 24 + (span / 24) * 0.14,
        width = (span / 24) * 0.72,
        height = (r.net_revenue / max) * plotH;
      body += `<rect x="${x}" y="${top + plotH - height}" width="${width}" height="${height}" rx="2" fill="${palette.teal}"><title>${esc(entity.label)} ${Number(r.hour)}点：${num(r.net_revenue)}元</title></rect>`;
      if (w > 600 || i % 2 === 0)
        body += svgText(
          x + width / 2,
          h - 12,
          Number(r.hour) + '时',
          `text-anchor="middle" class="dash-small"`,
        );
    });
    return svgRoot(w, h, `${entity.label}本周24小时收入，单位万元`, body);
  }
  function chartLegend(items = []) {
    return items.map(([label, color]) => `<span><i style="background:${color}"></i>${label}</span>`).join('');
  }

  function dashPanel(config) {
    const legends = {
      growth: [
        ['环比', palette.teal],
        ['同比', palette.blue],
      ],
      ranking: revenueLegend,
      platforms: [
        ['美团', palette.green],
        ['淘宝闪购', palette.purple],
        ['京东', palette.orange],
      ],
    };
    const legend = chartLegend(legends[config.id]);
    const detail = `<a class="dash-more" href="${route('chart', config.detailChart)}" aria-label="查看${esc(config.title)}详情">↗</a>`;
    const options =
      config.id === 'hourly'
        ? D.hourly_revenue_entities
            .map(
              (entity) =>
                `<option value="${esc(entity.key)}" ${entity.key === dashboardHour ? 'selected' : ''}>${esc(entity.label)}</option>`,
            )
            .join('')
        : '';
    return `<section class="dash-panel dash-${config.id}" style="--dash-span:${config.span}" data-dashboard-chart="${config.id}">
  <div class="dash-panel-head">
   <h2>${esc(config.title)}${config.id === 'hourly' ? '<small>万元</small>' : ''}</h2>
   ${options ? `<select id="dash-hour-select" aria-label="首页时段收入门店">${options}</select>` : detail}
  </div>
  ${legend ? `<div class="dash-legend">${legend}</div>` : ''}
  <div ${config.id === 'trend' ? 'id="dash-trend-host" class="dash-trend-host"' : `id="dash-plot-${config.id}" class="dash-plot"`}></div>
 </section>`;
  }
  const panels = STRUCTURE.dashboard.panels.filter(
    (panel) =>
      ({
        trend: D.availability.trend,
        ranking: rows.length,
        growth: rows.some(
          (row) => Number.isFinite(row.wow_net_revenue_pct) || Number.isFinite(row.yoy_net_revenue_pct),
        ),
        quadrants: rows.some((row) => Number.isFinite(row.wow_net_revenue_pct)),
        platforms: rows.some((row) =>
          ['meituan', 'eleme', 'jd'].some((key) =>
            Number.isFinite(row['current_' + key + '_delivery_revenue']),
          ),
        ),
        hourly: D.availability.dayparts,
      })[panel.id],
  );
  function diningSection(store = null) {
    const matches = (row) => store ? row.scope === 'store' && row['门店名称'] === store : row.scope === 'all';
    const total = X.dining?.weekly.find(matches);
    if (!total) return '';
    const cells = X.dining.daily.filter(matches);
    const measures = [
      ['堂食客流', 'dine_in_headcount', 'traffic_days', '人次', 0],
      ['估算翻台率', 'estimated_table_turnover', 'turnover_days', '轮/桌/天', 2],
    ];
    const show = (row, field, digits) => row[field] == null ? '—' : num(row[field], digits);
    const coverage = (row, key) => Number(row[key]) < Number(row.expected_store_days)
      ? `有数据 ${row[key]}/${row.expected_store_days} 个店日` : '';
    const cards = measures.map(([label, field, key, unit, digits]) => [
      label, total[field] == null ? '—' : show(total, field, digits) + ' ' + unit,
      coverage(total, key) || '本周',
    ]);
    if (total.dine_in_headcount == null && total.estimated_table_turnover == null
        && !Number(total.excluded_orders)) return '';
    const exceptions = Number(total.excluded_orders)
      ? `<p class="px-small-note">本周有 ${num(total.excluded_orders, 0)} 笔订单人数异常或不可用，已从客流剔除。${Number(total.excluded_registered_headcount) ? `可核对的原登记人数合计 ${num(total.excluded_registered_headcount, 0)} 人次。` : ''}</p>`
      : '';
    const days = cells.map((row) => `<tr><th scope="row">${esc(shortDate(row.business_date))}</th>${
      measures.map(([, field, key, , digits]) => {
        const note = coverage(row, key);
        return `<td>${show(row, field, digits)}${note ? `<small class="px-muted"> · ${esc(note)}</small>` : ''}</td>`;
      }).join('')
    }</tr>`).join('');
    return `<section class="px-section"><h2>堂食客流与翻台</h2>${kpis(cards)}${exceptions}${
      detail('逐日明细', `<div class="px-table-wrap"><table class="px-table" aria-label="堂食客流与翻台逐日明细"><thead><tr><th scope="col">营业日</th><th scope="col">客流（人次）</th><th scope="col">估算翻台（轮/桌/天）</th></tr></thead><tbody>${days}</tbody></table></div>`)
    }<p class="px-small-note">客流取已结账堂食订单的登记人数。翻台按堂食桌台使用次数除以系统配置桌日，含第一轮接待。</p></section>`;
  }

  function home(onlyStores = false) {
    if (onlyStores) {
      shell(`${heading('门店概览', '点击一家门店进入第二层')}${storeGrid()}`);
      bindSearch();
      return;
    }
    const totalOrders = dashSum('current_positive_orders'),
      previousOrders = dashSum('previous_positive_orders'),
      previousRevenue = dashSum('previous_net_revenue'),
      delivery = dashSum('current_delivery_revenue'),
      previousDelivery = dashSum('previous_delivery_revenue'),
      aov = D.kpis.current_revenue / totalOrders,
      previousAov = previousRevenue / previousOrders,
      share = delivery / D.kpis.current_revenue,
      previousShare = previousDelivery / previousRevenue;
    const comparable = rows.filter(
      (r) => Number.isFinite(r.yoy_net_revenue) && r.yoy_rows > 0 && r.current_rows > 0,
    );
    const sameCurrent = comparable.reduce((s, r) => s + r.current_net_revenue, 0),
      sameYoy = comparable.reduce((s, r) => s + r.yoy_net_revenue, 0);
    const cards = [
      [
        '订单营业收入',
        wan(D.kpis.current_revenue),
        `环比 ${pct(D.kpis.wow_pct)} · 可比${comparable.length}店同比 ${pct(deltaRatio(sameCurrent, sameYoy))}`,
      ],
      ['正向订单', num(totalOrders, 0) + ' 单', `环比 ${pct(deltaRatio(totalOrders, previousOrders))}`],
      ['折后单均', num(aov) + ' 元', `环比 ${pct(deltaRatio(aov, previousAov))}`],
      [
        '外卖收入占比',
        num(share * 100, 1) + '%',
        `较上周 ${share - previousShare >= 0 ? '+' : ''}${num((share - previousShare) * 100, 1)} 个百分点`,
      ],
    ];
    shell(
      `<div class="dash-title"><h1 tabindex="-1">周经营驾驶舱</h1><span>${esc(dateRange('current', true))} · ${rows.length} 家门店</span></div><div class="dash-verdict"><span>本周判断</span><p>${esc(content.headline)}</p><a href="${route('priorities')}">看依据 →</a></div>${D.availability.current ? kpis(cards) : '<p>本周暂无可用经营数据。</p>'}${diningSection()}<div class="dash-grid" style="--dash-columns:${STRUCTURE.dashboard.desktopColumns}">${panels.map(dashPanel).join('')}</div><section class="dash-store-section"><div class="dash-section-heading"><h2>进入门店</h2></div><div class="dash-store-links">${rows.map((r, i) => `<a href="${route('store', i)}"><b>${esc(short(r['门店名称']))}</b><span class="${r.wow_net_revenue_pct < 0 ? 'px-down' : 'px-up'}">${pct(r.wow_net_revenue_pct)} <i>环比</i></span><span aria-hidden="true">↗</span></a>`).join('')}</div></section>`,
    );
    if (document.getElementById('dash-trend-host')) {
      mount(trendNode, 'dash-trend-host');
      const select = document.getElementById('trendStoreSelect');
      select.value = dashboardTrendStore;
      if (!select.value) select.value = '__all__';
      select.dispatchEvent(new Event('change'));
      readableTrendTicks();
      dashboardTrendObserver = new MutationObserver(readableTrendTicks);
      dashboardTrendObserver.observe(document.getElementById('trend'), { childList: true, subtree: true });
    }
    const renderers = {
      ranking: dashboardRank,
      growth: dashboardGrowth,
      quadrants: dashboardQuadrants,
      platforms: dashboardPlatforms,
      hourly: dashboardHours,
    };
    function redraw(el) {
      const id = el.id.replace('dash-plot-', '');
      const w = Math.max(260, Math.floor(el.clientWidth));
      el.innerHTML = renderers[id](w);
    }
    dashboardObserver = new ResizeObserver((entries) => {
      readableTrendTicks();
      for (const e of entries) {
        const el = e.target;
        const w = Math.floor(e.contentRect.width);
        if (el.dataset.width !== String(w)) {
          el.dataset.width = w;
          redraw(el);
        }
      }
    });
    app.querySelectorAll('.dash-plot').forEach((el) => {
      redraw(el);
      dashboardObserver.observe(el);
    });
    const hourlySelect = document.getElementById('dash-hour-select');
    if (hourlySelect)
      hourlySelect.onchange = (e) => {
        dashboardHour = e.target.value;
        redraw(document.getElementById('dash-plot-hourly'));
      };
  }

  function store(i) {
    const r = rows[i],
      name = r['门店名称'];
    shell(
      `${storeCrumbs(i)}${heading(name, '先选择一个经营维度。详细表格与判断留在下一层。', 'STORE / 门店概览')}${kpis(
        [
          ['订单营业收入', wan(r.current_net_revenue), '本周'],
          ['收入环比', pct(r.wow_net_revenue_pct), '与上周相比'],
          ['正向订单', num(r.current_positive_orders, 0) + ' 单', '营业分组表口径'],
          ['折后单均', num(r.current_post_discount_aov) + ' 元', '同口径收入 / 正向订单'],
        ],
      )}${diningSection(name)}${summary(ptext(mealNode(name), 1))}<div class="px-modules">${link(route('meals', i), '餐段经营', '早餐、午餐、晚餐等餐段 → 关键指标 → 时段依据', '◷')}${link(route('menu', i), '菜品结构', '品类 → 具体菜品 → 原品项销量与渠道', '≋')}${link(route('orders', i), '堂食订单结构', '用餐人数分组 → 订单与收入变化', '▤')}${link(route('takeaway', i), '外卖渠道与费用', '平台 → 收入、单量、活动支出与退款', '↗')}${link(route('reviews', i), '顾客声音', '先读一句经营判断，再看主题与建议', '◎')}${link(route('trend', i), '收入趋势', '进入后查看本店完整历史，并缩放时间范围', '⌁')}</div>`,
    );
  }
  function evidenceGroups(name) {
    const n = mealNode(name),
      groups = {};
    for (const li of n?.querySelectorAll('.review-evidence li') ?? []) {
      const t = li.textContent;
      const g =
        ['早餐', '午餐', '下午餐', '晚餐', '夜餐', '未设置餐段'].find((x) => t.startsWith(x)) || '其他依据';
      (groups[g] ??= []).push(t);
    }
    return groups;
  }
  function meals(i, meal) {
    const name = rows[i]['门店名称'],
      node = mealNode(name),
      groups = evidenceGroups(name),
      allMeals = X.meals.filter((r) => r.store === name);
    if (meal) {
      const r = allMeals.find((r) => r.meal === meal);
      const vals = r.periods;
      const items = groups[meal] || [];
      shell(
        `${storeCrumbs(i, ['餐段经营', route('meals', i)], [meal])}${heading(meal + ' · 经营事实', '本店整餐段汇总；可继续进入具体时段。', 'MEAL / 第三层')}${kpis(
          [
            ['本周订单营业收入', wan(vals.current.revenue), '整餐段合计'],
            ['上周订单营业收入', wan(vals.previous.revenue), '同一餐段'],
            ['本周正向订单', num(vals.current.orders, 0) + ' 单', '整餐段合计'],
            ['本周折后单均', num(vals.current.aov) + ' 元', '收入 / 正向订单'],
          ],
        )}<div class="px-modules">${link(route('slots', i, meal), '继续看小时分布', '这个餐段本周、上周和同期的时段数值', '◷')}${link(route('meal-advice', i), '餐段判断与行动', '查看本店跨餐段的完整判断与下一步', '↗')}</div>${detail(
          '整餐段三期数值对照',
          table(
            ['指标', '本周', '上周', '去年同期'],
            [
              [
                '订单营业收入（元）',
                num(vals.current.revenue),
                num(vals.previous.revenue),
                num(vals.yoy.revenue),
              ],
              [
                '正向订单（单）',
                num(vals.current.orders, 0),
                num(vals.previous.orders, 0),
                num(vals.yoy.orders, 0),
              ],
              ['折后单均（元）', num(vals.current.aov), num(vals.previous.aov), num(vals.yoy.aov)],
            ],
          ),
        )}${
          items.length
            ? detail(
                '原报告引用的餐段依据',
                table(
                  ['指标', '数值'],
                  items.map((t) => {
                    const at = t.lastIndexOf('：');
                    return [esc(t.slice(0, at)), esc(t.slice(at + 1))];
                  }),
                ),
              )
            : ''
        }`,
      );
      return;
    }
    shell(
      `${storeCrumbs(i, ['餐段经营'])}${heading('餐段经营', '先看整体判断，再选择要核查的餐段。', 'OPERATIONS / 第二层')}${summary(ptext(node, 1))}<div class="px-modules">${allMeals.map((r) => link(route('meals', i, r.meal), r.meal, `本周收入 ${wan(r.periods.current.revenue)} · 上周 ${wan(r.periods.previous.revenue)}`, '◷')).join('')}${link(route('meal-advice', i), '经营判断与下一步', '本期表现、完整建议和全部引用依据', '↗')}${link(route('hourly', i), '全天时段图', '本店 24 小时收入分布', '⌁')}</div>`,
    );
  }
  function mealAdvice(i) {
    const n = mealNode(rows[i]['门店名称']);
    shell(
      `${storeCrumbs(i, ['餐段经营', route('meals', i)], ['判断与行动'])}${heading('餐段判断与行动', '沿用原报告的完整经营建议。')}${[...(n?.querySelectorAll(':scope>p') ?? [])].map((p) => `<div class="px-summary">${p.outerHTML}</div>`).join('')}${detail('查看全部引用依据', n?.querySelector('.review-evidence ul')?.outerHTML || '')}`,
    );
  }
  function slots(i, meal) {
    const rs = D.daypart_attribution.comparison
      .filter((r) => r['门店名称'] === rows[i]['门店名称'] && r['餐段'] === meal)
      .sort((a, b) => a['时段'].localeCompare(b['时段']));
    shell(
      `${storeCrumbs(i, ['餐段经营', route('meals', i)], [meal, route('meals', i, meal)], ['时段明细'])}${heading(meal + ' · 时段明细', '金额单位：元。时段用于定位变化，整餐段判断见上一层。')}${table(
        ['时段', '本周收入', '上周收入', '去年同期收入'],
        rs.map((r) => [
          esc(r['时段']),
          num(r.current_net_revenue),
          num(r.previous_net_revenue),
          num(r.yoy_net_revenue),
        ]),
      )}`,
    );
  }
  function advicePage(j, leaf) {
    const a = advice[j];
    const title = a.querySelector('summary').textContent.split(' · ').slice(2).join(' · ');
    const ps = [...a.querySelectorAll(':scope>p')];
    if (!leaf) {
      shell(
        `${crumbs([['本周关注'], [title]])}${heading(title, '先看判断，再进入行动安排或数值依据。', 'PRIORITY / 企业重点')}${summary(ptext(a, 1))}<div class="px-modules">${link(route('advice', j, 'why'), '为什么关注', '本期表现、经营判断和可能原因', '?')}${link(route('advice', j, 'action'), '下一步怎么做', '责任角色、范围、复盘指标与调整条件', '→')}${link(route('advice', j, 'evidence'), '查数值依据', '核对支持该判断的具体经营事实', '▤')}</div>`,
      );
      return;
    }
    const titles = { why: '判断与可能原因', action: '行动与验证', evidence: '数值依据' };
    const html =
      leaf === 'why'
        ? ps
            .slice(0, 3)
            .map((p) => p.outerHTML)
            .join('')
        : leaf === 'evidence'
          ? a.querySelector('ul').outerHTML
          : ps
              .slice(3)
              .map((p, k) => p.outerHTML + (k === 0 ? a.querySelector('ol')?.outerHTML || '' : ''))
              .join('');
    shell(
      `${crumbs([[title, route('advice', j)], [titles[leaf]]])}${heading(titles[leaf], title)}<div class="px-detail-body">${html}</div>`,
    );
  }
  function productValue(p, period, key) {
    const vals = Object.values(p.periods[period] || {});
    if (!vals.length || vals.some((x) => x[key] === null || x[key] === undefined)) return null;
    return vals.reduce((s, x) => s + Number(x[key]), 0);
  }
  function menu(i, category, productId) {
    const name = rows[i]['门店名称'];
    const ps = X.products.map((p, j) => ({ ...p, id: j })).filter((p) => p.store === name);
    if (productId !== undefined) {
      const p = X.products[Number(productId)];
      if (!p || p.store !== name) throw Error('Invalid product scope');
      const c = productValue(p, 'current', 'revenue'),
        pr = productValue(p, 'previous', 'revenue');
      shell(
        `${storeCrumbs(i, ['菜品结构', route('menu', i)], [p.category, route('menu', i, p.category)], [p.name])}${heading(p.name, '原品项独立保留；不同名称和规格不合并销量。', 'PRODUCT / 菜品详情')}${kpis(
          [
            ['本周菜品收入', wan(c), '菜品本身收入'],
            ['上周菜品收入', wan(pr), '未见记录显示 —'],
            ['本周销量', num(productValue(p, 'current', 'quantity')), '原品项单位'],
            ['上周销量', num(productValue(p, 'previous', 'quantity')), '原品项单位'],
          ],
        )}${table(
          ['订单分类', '本周销量', '上周销量', '本周收入（元）', '上周收入（元）'],
          [
            ...new Set([...Object.keys(p.periods.current || {}), ...Object.keys(p.periods.previous || {})]),
          ].map((ch) => [
            esc(ch),
            num(p.periods.current?.[ch]?.quantity),
            num(p.periods.previous?.[ch]?.quantity),
            num(p.periods.current?.[ch]?.revenue),
            num(p.periods.previous?.[ch]?.revenue),
          ]),
        )}<p class="px-small-note">关联菜品名称：${esc(p.linked || '未填写')}。${p.match === 'unique' ? '品类来自当前成本卡目录的唯一名称候选。' : p.match === 'ambiguous' ? '当前成本卡有多个同名候选；品类一致时仅采用共同品类，具体规格仍待确认。' : '暂无已确认的品类归属。'}${p.fee ? ' 本项为收费或餐具记录，不纳入实物动销判断。' : ''}</p>${summary('先核对本期和上期的在售名称、规格及可售情况，再解释销量变化；若只是名称或归类变化，修正比较对象后再决定动作。', '阅读与核查')}`,
      );
      return;
    }
    if (category) {
      const list = ps
        .filter((p) => p.category === category)
        .sort(
          (a, b) =>
            (productValue(b, 'current', 'revenue') ?? -Infinity) -
            (productValue(a, 'current', 'revenue') ?? -Infinity),
        );
      shell(
        `${storeCrumbs(i, ['菜品结构', route('menu', i)], [category])}${heading(category, `${list.length} 个原品项记录 · 选择一个菜品进入销量、收入与渠道明细。`)}<div class="px-tools" style="margin-bottom:16px"><input id="px-product-search" aria-label="搜索菜品" placeholder="搜索菜品名称"></div><div class="px-stores" id="px-products"></div><div class="px-tools" id="px-product-paging" style="margin-top:16px"></div>`,
      );
      const memory = listStates.get(lastRoute) || { page: 0, query: '' };
      let page = memory.page;
      const input = document.getElementById('px-product-search');
      input.value = memory.query;
      function paint() {
        listStates.set(lastRoute, { page, query: input.value });
        const filtered = list.filter((p) => p.name.includes(input.value) || p.linked.includes(input.value));
        const part = filtered.slice(page * 12, page * 12 + 12);
        document.getElementById('px-products').innerHTML =
          part
            .map(
              (p) =>
                `<a class="px-store" href="${route('menu', i, category, p.id)}"><h3>${esc(p.name)}</h3><div class="px-store-revenue"><strong>${wan(productValue(p, 'current', 'revenue'))}</strong><span>本周菜品收入</span></div><p>上周 ${wan(productValue(p, 'previous', 'revenue'))}</p>${p.linked && p.linked !== p.name ? `<p>关联：${esc(p.linked)}</p>` : ''}<div class="px-store-foot">查看销量与渠道 →</div></a>`,
            )
            .join('') || '<p>没有匹配菜品</p>';
        document.getElementById('px-product-paging').innerHTML =
          `<button id="px-prev" ${page === 0 ? 'disabled' : ''}>上一页</button><span class="px-muted">${page + 1} / ${Math.max(1, Math.ceil(filtered.length / 12))} · ${filtered.length} 项</span><button id="px-next" ${(page + 1) * 12 >= filtered.length ? 'disabled' : ''}>下一页</button>`;
        document.getElementById('px-prev').onclick = () => {
          page--;
          paint();
        };
        document.getElementById('px-next').onclick = () => {
          page++;
          paint();
        };
      }
      input.oninput = () => {
        page = 0;
        paint();
      };
      paint();
      return;
    }
    const cats = [...new Set(ps.map((p) => p.category))];
    const leaders = ps
      .filter((p) => !p.fee && productValue(p, 'current', 'revenue') !== null)
      .sort((a, b) => productValue(b, 'current', 'revenue') - productValue(a, 'current', 'revenue'));
    shell(
      `${storeCrumbs(i, ['菜品结构'])}${heading('菜品结构', '按可核验品类组织，其余保留待确认。', 'MENU / 第二层')}${leaders.length ? summary(`${leaders[0].name}本周菜品收入为 ${wan(productValue(leaders[0], 'current', 'revenue'))}元。`, '本店收入最高的实物品项') : ''}${ptext(reviews.get(name)?.querySelector('[data-review-section="dishes"]'), 1) ? summary(ptext(reviews.get(name)?.querySelector('[data-review-section="dishes"]'), 1), '经营判断') : ''}<div class="px-modules">${cats.map((c) => link(route('menu', i, c), c, `${ps.filter((p) => p.category === c).length} 个原品项记录 · 本周收入 ${wan(ps.filter((p) => p.category === c).reduce((s, p) => s + (productValue(p, 'current', 'revenue') || 0), 0))}`, '≋')).join('')}</div><p class="px-small-note">本页为基础品类视角，不等同于厨房档口。当前目录用于导航，不回溯认定上周所属档口。金额为菜品本身收入，不与总览订单营业收入相加。</p>`,
    );
  }
  function orders(i, group) {
    const row = rows[i],
      name = row['门店名称'];
    if (!X.orders.some((item) => item.store === name)) {
      shell(
        `${storeCrumbs(i, ['堂食订单结构'])}${heading('堂食订单结构', '营业汇总口径', 'ORDERS / 堂食')}${table(
          ['指标', '本周', '上周'],
          [
            [
              '正向订单',
              num(row.current_dine_in_positive_orders, 0),
              num(row.previous_dine_in_positive_orders, 0),
            ],
            ['订单营业收入（元）', num(row.current_dine_in_revenue), num(row.previous_dine_in_revenue)],
          ],
        )}<p class="px-small-note">用餐人数分组需同周已结账订单明细。</p>`,
      );
      return;
    }
    const rs = X.orders.filter((r) => r.store === name);
    const gs = [...new Set(rs.map((r) => r.group))].sort((a, b) => a.localeCompare(b, 'zh-CN'));
    const c = (g) => rs.find((x) => x.period === 'current' && x.group === g);
    const p = (g) => rs.find((x) => x.period === 'previous' && x.group === g);
    if (group) {
      shell(
        `${storeCrumbs(i, ['堂食订单结构', route('orders', i)], [group])}${heading(group + ' · 堂食已结账订单', '按源表用餐人数分组，保留已结账范围。')}${table(
          ['指标', '本周', '上周'],
          [
            ['记录数', num(c(group)?.records, 0), num(p(group)?.records, 0)],
            ['订单收入（元）', num(c(group)?.income), num(p(group)?.income)],
            [
              '每条记录平均收入（元）',
              c(group) ? num(Number(c(group).income) / c(group).records) : '—',
              p(group) ? num(Number(p(group).income) / p(group).records) : '—',
            ],
            ['订单优惠（元）', num(c(group)?.discount), num(p(group)?.discount)],
          ],
        )}<p class="px-small-note">本周 ${esc(dateRange('current'))}，上周 ${esc(dateRange('previous'))}。订单明细与营业汇总分别呈现，不重复加总收入。</p>`,
      );
      return;
    }
    shell(
      `${storeCrumbs(i, ['堂食订单结构'])}${heading('堂食订单结构', '从总收入变化，进一步看不同用餐人数的订单。', 'ORDERS / 新增数据')}${summary('按已结账堂食订单的用餐人数分组，比较本周和上周。', '统计口径')}<div class="px-modules">${gs.map((g) => link(route('orders', i, g), g, `本周 ${num(c(g)?.records, 0)} 条 · 上周 ${num(p(g)?.records, 0)} 条；收入 ${wan(c(g)?.income)}`, '▤')).join('')}</div><p class="px-small-note">仅使用用餐方式为“堂食”的已结账记录；人数分组不等同于桌台类型，不据此推算取消率或未结账损失。</p>`,
    );
  }
  function takeaway(i, platform) {
    const row = rows[i],
      name = row['门店名称'],
      rs = X.takeaway.filter((r) => r.store === name);
    if (!rs.length) {
      const channels = [
        ['美团', 'meituan'],
        ['饿了么／淘宝闪购', 'eleme'],
        ['京东', 'jd'],
      ];
      shell(
        `${storeCrumbs(i, ['外卖渠道与费用'])}${heading('外卖渠道与费用', '营业汇总口径', 'DELIVERY / 外卖')}${table(
          ['平台收入（元）', '本周', '上周'],
          channels.map(([label, key]) => [
            label,
            num(row['current_' + key + '_delivery_revenue']),
            num(row['previous_' + key + '_delivery_revenue']),
          ]),
        )}<p class="px-small-note">费用、退款与订单状态需同周平台订单明细。</p>`,
      );
      return;
    }
    const gs = [...new Set(rs.map((r) => r.group))];
    const get = (p, w) => rs.find((r) => r.group === p && r.period === w);
    if (platform) {
      const c = get(platform, 'current'),
        p = get(platform, 'previous');
      shell(
        `${storeCrumbs(i, ['外卖渠道与费用', route('takeaway', i)], [platform])}${heading(platform + ' · 收入与费用', '费用保留源表口径，可用于核查增长质量。', 'CHANNEL / 平台详情')}${table(
          ['指标', '本周', '上周'],
          [
            ['订单记录数', num(c?.records, 0), num(p?.records, 0)],
            ...[
              ['income', '营业收入（元）'],
              ['platform_fee', '平台服务费（元）'],
              ['promotion', '商家活动支出（元）'],
              ['refund', '部分退款（元）'],
              ['customer_paid', '顾客实付（元）'],
            ].map(([k, l]) => [l, num(c?.[k]), num(p?.[k])]),
          ],
        )}${detail(
          '查看订单状态范围',
          `<p>本周：${esc(
            Object.entries(c?.statuses || {})
              .map(([k, v]) => `${k} ${v} 条`)
              .join('；'),
          )}</p><p>上周：${esc(
            Object.entries(p?.statuses || {})
              .map(([k, v]) => `${k} ${v} 条`)
              .join('；'),
          )}</p>`,
        )}<p class="px-small-note">费用、收入和顾客实付是不同源字段，不重复扣减，也不据此称为利润；包含源表有效订单范围内尚未完成的记录。</p>`,
      );
      return;
    }
    shell(
      `${storeCrumbs(i, ['外卖渠道与费用'])}${heading('外卖渠道与费用', '先选择平台，再查看费用、退款与订单状态。', 'DELIVERY / 新增数据')}<div class="px-modules">${gs.map((g) => link(route('takeaway', i, g), g, `本周营业收入 ${wan(get(g, 'current')?.income)}；${num(get(g, 'current')?.records, 0)} 条订单记录`, '↗')).join('')}</div>${summary('营业收入、商家活动支出和退款按平台分别汇总。', '统计口径')}`,
    );
  }
  function voiceStore(i) {
    return V?.stores.find((s) => s.store_name === rows[i]['门店名称']);
  }
  function voiceIndex(name) {
    return rows.findIndex((r) => r['门店名称'] === name);
  }
  const voiceTone = (t) => ({ keep: '值得保持', priority: '优先核实', check: '先做核查' })[t];
  function voiceCloud(items) {
    return `<div class="px-wordcloud" aria-label="本周评价主题词云">${items.map((v, j) => `<a class="px-cloud-${v.tone} px-cloud-size-${v.tone === 'priority' ? 0 : v.tone === 'check' ? 1 : 2}" href="${v.href}">${esc(v.label)}</a>`).join('')}</div><p class="px-small-note">绿色为值得保持，暖色为待核查；字号仅强调阅读重点，不表示提及次数或满意率。</p>`;
  }
  function customerReviews(key) {
    if (key === 'all') {
      if (!V) {
        shell(`${crumbs([['顾客声音']])}${heading('顾客声音', '本期暂无可分析的评价正文。')}`);
        return;
      }
      const themes = V.stores.flatMap((store) =>
        store.themes.map((theme) => ({ ...theme, store_name: store.store_name })),
      );
      const priorities = themes
        .filter((theme) => theme.tone === 'check')
        .slice(0, 3)
        .map((theme) => ({
          title: theme.title,
          reason: theme.judgment,
          store_name: theme.store_name,
          theme_id: theme.id,
        }));
      const clouds = themes
        .slice(0, 8)
        .map((theme) => ({
          label: theme.cloud_label,
          tone: theme.tone,
          href: route('review-topic', voiceIndex(theme.store_name), theme.id),
        }));
      shell(
        `${crumbs([['顾客声音']])}${heading('顾客记住了什么，哪里值得先改。', '先读经营判断，再按门店查看主题；原文只在证据层出现。', 'VOICE / 经营解读')}${summary(V.overview, '本周判断')}<section class="px-section"><div class="px-section-head"><h2>本周先看这三件事</h2></div><div class="px-priorities">${priorities.map((p) => `<a class="px-priority" href="${route('review-topic', voiceIndex(p.store_name), p.theme_id)}"><span class="px-muted">建议核查</span><h3>${esc(p.title)}</h3><p>${esc(p.reason)}</p><span class="px-link">看判断与行动 →</span></a>`).join('')}</div></section><section class="px-section"><h2>一眼看见本周的主题</h2>${voiceCloud(clouds)}</section><section class="px-section"><div class="px-section-head"><h2>逐店读一句话</h2><p>选择门店，继续看值得保持和优先核查的事</p></div><div class="px-stores">${V.stores.map((s) => `<a class="px-store px-voice-store" href="${route('reviews', voiceIndex(s.store_name))}"><span class="px-muted">${esc(short(s.store_name))}</span><h3>${esc(s.headline)}</h3><div class="px-store-foot">进入本店解读 →</div></a>`).join('')}</div></section><p class="px-small-note">只基于本周已同步评价，保留正反反馈并合并相同正文。评价是核查线索，不直接解释营业变化。</p>`,
      );
      return;
    }
    const i = Number(key),
      s = voiceStore(i);
    if (!s) {
      shell(`${storeCrumbs(i, ['顾客声音'])}${heading('顾客声音', '本店本期暂无可分析的评价正文。')}`);
      return;
    }
    const priority =
      s.themes.find((t) => t.tone === 'priority') || s.themes.find((t) => t.tone === 'check') || s.themes[0];
    shell(
      `${storeCrumbs(i, ['顾客声音'])}${heading(s.headline, s.store_name, 'VOICE / 本店判断')}${priority ? summary(priority.judgment, '怎么看') : ''}${voiceCloud(s.themes.map((t) => ({ label: t.cloud_label, tone: t.tone, href: route('review-topic', i, t.id) })))}<div class="px-voice-lanes">${[
        'keep',
        'check',
      ]
        .map(
          (lane) =>
            `<section><div class="px-section-head"><h2>${lane === 'keep' ? '值得保持' : '优先核查'}</h2></div>${s.themes
              .filter((t) => (lane === 'keep' ? t.tone === 'keep' : t.tone !== 'keep'))
              .map(
                (t) =>
                  `<a class="px-voice-theme ${t.tone}" href="${route('review-topic', i, t.id)}"><span class="px-muted">${voiceTone(t.tone)}</span><h3>${esc(t.title)}</h3><p>${esc(t.judgment)}</p><span class="px-link">看具体观察与建议 →</span></a>`,
              )
              .join('')}</section>`,
        )
        .join(
          '',
        )}</div>${priority ? summary(priority.action, '下周先做一件事') : ''}<p class="px-small-note">这里给出经营解读；需要核对时，进入相应主题查看证据。相同正文已合并，不将纯评分解释成具体菜品意见。</p>`,
    );
  }
  function voiceTopic(i, id, evidence = false) {
    const s = voiceStore(i),
      t = s.themes.find((t) => t.id === id);
    if (!t) throw Error('Unknown review theme');
    const path = storeCrumbs(
      i,
      ['顾客声音', route('reviews', i)],
      [t.title, evidence ? route('review-topic', i, id) : null],
      ...(evidence ? [['引用依据']] : []),
    );
    if (!evidence) {
      shell(
        `${path}${heading(t.title, voiceTone(t.tone), 'VOICE / 主题解读')}${summary(t.judgment, '经营判断')}<div class="px-voice-analysis"><article><span class="px-kicker">OBSERVATION</span><h2>顾客实际说了什么</h2><p>${esc(t.observation)}</p></article><article><span class="px-kicker">NEXT ACTION</span><h2>建议怎么处理</h2><p>${esc(t.action)}</p></article></div><a class="px-evidence-link" href="${route('review-evidence', i, id)}">需要核对？查看支持这项判断的原文 →</a>`,
      );
      return;
    }
    shell(`${path}${heading('这项判断的引用依据', t.title, 'EVIDENCE / 最深一层')}${summary(t.observation, '要核对的观察')}
 ${t.evidence.map((item) => `<article class="px-quote-card"><div class="px-muted">${esc(item.source)} · ${esc(item.date)}</div><blockquote class="px-review-quote">${esc(item.excerpt)}</blockquote></article>`).join('')}`);
  }

  function originalChart(kind, i) {
    const isTrend = kind === 'trend',
      node = isTrend ? trendNode : hourlyNode;
    const title = isTrend ? '收入趋势' : '全天时段收入';
    shell(
      `${i === 'all' ? crumbs([[title]]) : storeCrumbs(Number(i), [title])}${heading(title, '可使用图表中的门店与时间控件继续探索。')}<div id="px-mount" class="px-original"></div>`,
    );
    mount(node);
    const select = document.getElementById(isTrend ? 'trendStoreSelect' : 'hourlyStoreSelect');
    const label = i === 'all' ? '全体门店' : rows[Number(i)]['门店名称'];
    const opt = [...select.options].find((o) => o.textContent === label);
    if (opt) {
      select.value = opt.value;
      select.dispatchEvent(new Event('change'));
    }
  }
  function design() {
    shell(`${crumbs([['数据说明']])}${heading('数据说明')}
 ${table(
   ['数据', '查看位置', '口径'],
   [
     ['营业汇总', '首页、门店、跨店专题', '订单营业收入、正向订单、折后单均与外卖收入占比'],
     ['菜品销售', '门店 → 菜品结构', '保留原始品项与渠道，按可核验品类导航'],
     [
       '堂食与外卖订单',
       '门店 → 堂食订单结构或外卖渠道与费用',
       '有同域明细时展示用餐人数、平台费用和订单状态',
     ],
     ['顾客评价', '顾客声音 → 主题 → 引用依据', '本周已同步评价，引用最小正文片段'],
   ],
 )}`);
  }
  function navigate() {
    if (lastRoute)
      saved.set(lastRoute, {
        scroll: scrollY,
        opens: [...app.querySelectorAll('details')].map((x) => x.open),
      });
    restore();
    const hash = location.hash;
    let path = hash.startsWith('#/alpha/') ? hash.slice(8).split('/').map(decodeURIComponent) : ['home'];
    const [page, arg, arg2, arg3] = path;
    const routeRule = resolveRoute(path);
    lastRoute = hash;
    activeRouteId = routeRule?.id;
    try {
      if (!routeRule) throw Error('Unregistered page structure');
      if (page === 'home' || !page) home();
      else if (page === 'allstores') home(true);
      else if (page === 'priorities')
        shell(
          `${crumbs([['经营建议']])}${heading('本周经营建议', '选择一个问题，再查看判断、行动与依据。')}${priorityCards()}<section class="px-section">${link(route('reviews', 'all'), '顾客声音解读', '逐店看值得保持与优先核查的体验问题', '◎')}</section>`,
        );
      else if (page === 'store') store(Number(arg));
      else if (page === 'meals') meals(Number(arg), arg2);
      else if (page === 'meal-advice') mealAdvice(Number(arg));
      else if (page === 'slots') slots(Number(arg), arg2);
      else if (page === 'advice') advicePage(Number(arg), arg2);
      else if (page === 'menu') menu(Number(arg), arg2, arg3);
      else if (page === 'orders') orders(Number(arg), arg2);
      else if (page === 'takeaway') takeaway(Number(arg), arg2);
      else if (page === 'reviews') customerReviews(arg);
      else if (page === 'review-topic') voiceTopic(Number(arg), arg2);
      else if (page === 'review-evidence') voiceTopic(Number(arg), arg2, true);
      else if (page === 'trend' || page === 'hourly') originalChart(page, arg);
      else if (page === 'design') design();
      else if (page === 'topics')
        shell(`${crumbs([['经营专题']])}${heading('跨店看经营', '先选问题，再进入对应图表。')}${topics()}`);
      else if (page === 'trends')
        shell(
          `${crumbs([['收入趋势']])}${heading('看整体，或看一家门店', '进入后可缩放时间、切换日／周／月。')}<div class="px-modules">${link(route('trend', 'all'), '全体门店', '企业合计收入趋势', '⌁')}${rows.map((r, i) => link(route('trend', i), short(r['门店名称']), '本店收入趋势', '⌁')).join('')}</div>`,
        );
      else if (page === 'benchmark')
        shell(
          `${crumbs([['跨店经营专题']])}${heading('跨店经营专题', '这里只展示问题入口；选择以后再显示具体图表。')}<div class="px-modules">${charts.map((c, i) => (i === 6 || c.node.closest('section')?.hidden ? '' : link(route('chart', i), i === 1 ? STRUCTURE.dashboard.panels.find((panel) => panel.id === 'ranking').title : c.title, '', '▥'))).join('')}</div>`,
        );
      else if (page === 'chart' && ['1', '6'].includes(arg)) rankedRevenueDetail();
      else if (page === 'chart') {
        const c = charts[Number(arg)];
        shell(
          `${crumbs([['跨店经营专题', route('benchmark')], [c.title]])}${heading(c.title)}<div class="px-original" id="px-mount"></div>`,
        );
        mount(c.node);
      } else if (page === 'original') {
        shell(
          `${crumbs([['原版完整报告']])}${heading('原版完整报告', '保留原始内容、图表与交互，供对照。')}<div class="px-full-tools"><button id="px-expand-all">展开原版全部内容</button><button id="px-collapse-all">收起原版详情</button></div>`,
        );
        original.classList.add('px-full');
        document.getElementById('px-expand-all').onclick = () =>
          original.querySelectorAll('details').forEach((d) => (d.open = true));
        document.getElementById('px-collapse-all').onclick = () =>
          original.querySelectorAll('details').forEach((d) => (d.open = false));
      } else home();
      app.dataset.page = routeRule.id;
      app.dataset.depth = routeRule.depth;
      app.dataset.template = routeRule.template;
      if (
        ['overview', 'store_index', 'store_overview', 'voice_overview', 'voice_store'].includes(
          routeRule.template,
        ) &&
        app.querySelector('.px-data-cards,table,.px-review-quote')
      )
        throw Error('Summary view contains deep content');
      if (
        routeRule.template === 'dashboard' &&
        (app.querySelectorAll('[data-dashboard-chart]').length !== panels.length ||
          app.querySelector('.px-priorities,.px-review-quote,.px-data-cards,table'))
      )
        throw Error('Dashboard content contract violated');
      if (routeRule.template !== 'voice_evidence' && app.querySelector('.px-review-quote'))
        throw Error('Review quotes escaped evidence view');
    } catch (e) {
      shell(`${crumbs([['页面未找到']])}${heading('此路径不可用', '请返回总览重新选择门店或模块。')}`);
      console.error(e);
    }
    const state = saved.get(hash);
    if (state) app.querySelectorAll('details').forEach((x, i) => (x.open = Boolean(state.opens[i])));
    app.querySelector('h1')?.focus({ preventScroll: true });
    window.scrollTo(0, state?.scroll || 0);
  }
  window.addEventListener('hashchange', navigate);
  document.addEventListener('click', (e) => {
    const a = e.target.closest('a[href^="#"]');
    if (a && a.closest('main') && !a.hash.startsWith('#/alpha/')) {
      const target = document.getElementById(a.hash.slice(1));
      if (target) {
        e.preventDefault();
        for (let n = target; n; n = n.parentElement) if (n.tagName === 'DETAILS') n.open = true;
        target.scrollIntoView({ block: 'start' });
      }
    }
  });
  let printState = [];
  window.addEventListener('beforeprint', () => {
    restore();
    document.body.classList.add('px-print');
    printState = [...original.querySelectorAll('details')].map((d) => d.open);
    original.querySelectorAll('details').forEach((d) => (d.open = true));
  });
  window.addEventListener('afterprint', () => {
    document.body.classList.remove('px-print');
    original.querySelectorAll('details').forEach((d, i) => (d.open = printState[i]));
    navigate();
  });
  navigate();
})();
