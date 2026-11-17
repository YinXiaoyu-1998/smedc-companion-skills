(() => {
  'use strict';
  const D = JSON.parse(document.getElementById('report-data').textContent);
  const content = JSON.parse(document.getElementById('weekly-dashboard-content').textContent);
  const legacy = document.querySelector('body > main');
  const { meta, availability, kpis } = D;
  const rows = D.comparison.filter((row) => row.current_rows > 0);
  const groups = D.segment_groups.filter((group) => rows.some((row) => row.store_size === group.key));
  const voice = content.customer_voice;
  const advisory = content.advisory;
  const esc = (value) =>
    String(value ?? '').replace(
      /[&<>"']/g,
      (ch) =>
        ({
          '&': '&amp;',
          '<': '&lt;',
          '>': '&gt;',
          '"': '&quot;',
          "'": '&#39;',
        })[ch],
    );
  const num = (value, digits = 2) =>
    Number.isFinite(value)
      ? value.toLocaleString('zh-CN', {
          minimumFractionDigits: digits,
          maximumFractionDigits: digits,
        })
      : '—';
  const pct = (value) => (Number.isFinite(value) ? (value >= 0 ? '+' : '') + num(value * 100, 1) + '%' : '—');
  const wan = (value) => (Number.isFinite(value) ? num(value / 10000) + ' 万' : '—');
  const short = (name) => {
    const match = name.match(/[（(]([^）()]+)[）)]$/);
    return match ? match[1] : name;
  };
  const path = (...parts) => '#/weekly/' + parts.map(encodeURIComponent).join('/');
  const chartLink = (index, label, body) =>
    `<a href="${path('store', index)}" aria-label="${esc(label)}"><title>${esc(label)}</title>${body}</a>`;
  const link = (target, text) =>
    `<a class="week-card-link" href="${target}">${esc(text)} <span aria-hidden="true">↗</span></a>`;
  const ratio = (numerator, denominator) =>
    Number.isFinite(numerator) && Number.isFinite(denominator) && denominator !== 0
      ? numerator / denominator
      : null;
  const change = (value, previous) =>
    Number.isFinite(value) && Number.isFinite(previous) ? ratio(value - previous, previous) : null;
  const sum = (list, key) =>
    list.length && list.every((row) => Number.isFinite(row[key]))
      ? list.reduce((total, row) => total + row[key], 0)
      : null;
  const heading = (title) => `<h1 tabindex="-1">${esc(title)}</h1>`;
  const title = (label, amount, comparison = '') =>
    `<div class="week-kpi"><span>${esc(label)}</span><strong>${esc(amount)}</strong><small>${esc(comparison)}</small></div>`;
  const money = (value) => (Number.isFinite(value) ? num(value) + ' 元' : '—');
  const integer = (value) => (Number.isFinite(value) ? num(value, 0) + ' 单' : '—');
  let dashboardHour = '__all__';
  let collapsed = false;
  let drawer = false;
  let trendStore = '__all__';
  let observer;
  let mounted;
  const mobile = matchMedia('(max-width: 820px)');
  const app = document.createElement('div');
  app.id = 'weekly-app';
  document.body.insertBefore(app, legacy);
  const trend = document.getElementById('trend')?.closest('.panel');

  /*__WEEKLY_CHARTS__*/

  const charts = [
    { id: 'trend', label: '收入趋势', width: 6, available: availability.trend, element: trend },
    {
      id: 'ranking',
      label: '门店收入排名及堂食／外卖结构',
      width: 5,
      available: rows.length,
      render: dashboardRank,
      legend: revenueLegend,
    },
    {
      id: 'growth',
      label: '门店收入环比／同比',
      width: 5,
      available: rows.some(
        (r) => Number.isFinite(r.wow_net_revenue_pct) || Number.isFinite(r.yoy_net_revenue_pct),
      ),
      render: dashboardGrowth,
      legend: [
        ['环比', palette.teal],
        ['同比', palette.blue],
      ],
    },
    {
      id: 'quadrants',
      label: '门店经营四象限',
      width: 6,
      available: groups.length && rows.some((r) => Number.isFinite(r.wow_net_revenue_pct)),
      render: dashboardQuadrants,
    },
    {
      id: 'platforms',
      label: '外卖平台收入',
      width: 5,
      available: rows.some((r) =>
        [
          'current_meituan_delivery_revenue',
          'current_eleme_delivery_revenue',
          'current_jd_delivery_revenue',
        ].some((key) => Number.isFinite(r[key])),
      ),
      render: dashboardPlatforms,
      legend: [
        ['美团', palette.green],
        ['饿了么／淘宝闪购', palette.purple],
        ['京东', palette.orange],
      ],
    },
    {
      id: 'hourly',
      label: '24小时收入分布',
      width: 5,
      available: availability.dayparts && D.hourly_revenue_entities.some((entity) => entity.rows.length),
      render: dashboardHours,
    },
  ].filter((chart) => chart.available);

  function syncNav() {
    document.body.classList.toggle('week-sidebar-small', collapsed && !mobile.matches);
    document.body.classList.toggle('week-drawer-open', drawer && mobile.matches);
    const sidebar = document.getElementById('week-sidebar');
    sidebar.inert = mobile.matches && !drawer;
    document
      .getElementById('week-sidebar-toggle')
      .setAttribute('aria-expanded', String(mobile.matches ? drawer : !collapsed));
    document.getElementById('week-mobile-toggle').setAttribute('aria-expanded', String(drawer));
  }
  function closeDrawer() {
    drawer = false;
    syncNav();
    document.getElementById('week-mobile-toggle').focus();
  }
  function shell(body, page = 'home') {
    const links = [
      ['home', '总览', '▦'],
      ['stores', '门店', '▤'],
      ['advice', '经营建议', '✓'],
      ...(voice ? [['voice', '顾客声音', '◉']] : []),
      ['topics', '跨店专题', '▥'],
    ];
    const active =
      page === 'store' || page === 'store-section' ? 'stores' : page === 'chart' ? 'topics' : page;
    drawer = false;
    app.innerHTML = `
   <aside id="week-sidebar" class="week-sidebar" aria-label="周报导航">
    <div class="week-sidebar-head"><a class="week-brand" href="${path('home')}" aria-label="${esc(meta.company)}"><b aria-hidden="true">周</b><span>${esc(meta.company)}</span></a>
    <button id="week-sidebar-toggle" aria-label="收起或展开侧栏" aria-controls="week-nav" type="button">☰</button></div>
    <nav id="week-nav" aria-label="主导航">${links.map(([key, label, icon]) => `<a href="${path(key)}" title="${label}" aria-label="${label}" ${active === key ? 'aria-current="page"' : ''}><b aria-hidden="true">${icon}</b><span>${label}</span></a>`).join('')}</nav>
   </aside>
   <button class="week-scrim" type="button" aria-label="关闭导航" tabindex="-1"></button>
   <header class="week-mobile-head"><button id="week-mobile-toggle" type="button" aria-label="打开导航" aria-controls="week-sidebar">☰</button>${esc(meta.company)}</header>
   <div class="week-content ${page === 'home' ? 'week-home' : ''}">${body}<footer>${esc(meta.target_windows.current.start)} — ${esc(meta.target_windows.current.end)} · 订单营业收入</footer></div>`;
    syncNav();
    document.getElementById('week-sidebar-toggle').onclick = () => {
      if (mobile.matches) closeDrawer();
      else {
        collapsed = !collapsed;
        syncNav();
      }
    };
    document.getElementById('week-mobile-toggle').onclick = () => {
      drawer = true;
      syncNav();
      document.getElementById('week-sidebar-toggle').focus();
    };
    app.querySelector('.week-scrim').onclick = closeDrawer;
    app.querySelectorAll('#week-sidebar a').forEach(
      (item) =>
        (item.onclick = () => {
          if (drawer && item.hash === location.hash) closeDrawer();
        }),
    );
  }

  function storeLinks() {
    return `<section class="week-store-list"><h2>进入门店</h2><div>${rows
      .map(
        (row, index) =>
          `<a class="week-card-link" href="${path('store', index)}"><b>${esc(short(row['门店名称']))}</b><small>${pct(row.wow_net_revenue_pct)} 环比</small></a>`,
      )
      .join('')}</div></section>`;
  }

  function chartPanel(chart, expanded = false) {
    const legend = chartLegend(chart.legend);
    return `<section class="week-panel week-panel-${chart.id}" style="--week-span:${chart.width}" data-week-chart="${chart.id}">
   <header><h2>${chart.label}${chart.id === 'hourly' ? '<small>万元</small>' : ''}</h2>
    ${chart.id === 'hourly' ? `<select aria-label="时段收入门店">${D.hourly_revenue_entities.map((entity) => `<option value="${esc(entity.key)}" ${entity.key === dashboardHour ? 'selected' : ''}>${esc(entity.label)}</option>`).join('')}</select>` : expanded ? '' : `<a href="${path('chart', chart.id)}" aria-label="查看${chart.label}详情">↗</a>`}</header>
   ${legend ? `<div class="week-legend">${legend}</div>` : ''}
   <div class="${chart.element ? 'week-trend' : 'dash-plot'}" id="week-plot-${chart.id}"></div></section>`;
  }

  function attachCharts(chosen) {
    observer = new ResizeObserver((entries) => entries.forEach(({ target }) => draw(target)));
    function draw(target) {
      const width = Math.floor(target.clientWidth);
      if (!width || target.dataset.width === String(width)) return;
      target.dataset.width = String(width);
      target.innerHTML = chosen
        .find((chart) => target.id === `week-plot-${chart.id}`)
        .render(Math.max(230, width));
    }
    for (const chart of chosen) {
      const plot = document.getElementById(`week-plot-${chart.id}`);
      if (chart.element) {
        mount(chart.element, plot);
        const selector = document.getElementById('trendStoreSelect');
        selector.value = trendStore;
        if (selector.value) selector.dispatchEvent(new Event('change'));
      } else {
        draw(plot);
        observer.observe(plot);
      }
    }
    const hourly = app.querySelector('.week-panel-hourly select');
    if (hourly)
      hourly.onchange = () => {
        dashboardHour = hourly.value;
        const plot = document.getElementById('week-plot-hourly');
        delete plot.dataset.width;
        draw(plot);
      };
  }
  function mount(node, destination) {
    const anchor = document.createComment('weekly-panel');
    node.before(anchor);
    destination.append(node);
    mounted = { node, anchor };
  }
  function restore() {
    observer?.disconnect();
    if (mounted) {
      if (mounted.node === trend) trendStore = document.getElementById('trendStoreSelect').value;
      mounted.anchor.replaceWith(mounted.node);
      mounted = null;
    }
  }
  function home() {
    const previousRevenue = sum(
      D.comparison.filter((row) => row.previous_rows > 0),
      'previous_net_revenue',
    );
    const orders = sum(rows, 'current_positive_orders');
    const previousOrders = sum(
      D.comparison.filter((row) => row.previous_rows > 0),
      'previous_positive_orders',
    );
    const deliveryShare = ratio(sum(rows, 'current_delivery_revenue'), kpis.current_revenue);
    const previousDeliveryShare = ratio(
      sum(
        D.comparison.filter((row) => row.previous_rows > 0),
        'previous_delivery_revenue',
      ),
      previousRevenue,
    );
    const shareDifference =
      Number.isFinite(deliveryShare) && Number.isFinite(previousDeliveryShare)
        ? (deliveryShare - previousDeliveryShare) * 100
        : null;
    const comparable = rows.filter((row) => row.yoy_rows > 0 && Number.isFinite(row.yoy_net_revenue));
    const comparableChange = change(
      sum(comparable, 'current_net_revenue'),
      sum(comparable, 'yoy_net_revenue'),
    );
    const comparison = [
      '环比 ' + pct(kpis.wow_pct),
      ...(comparableChange === null ? [] : [`可比${comparable.length}店同比 ${pct(comparableChange)}`]),
    ].join(' · ');
    const verdict = content.headline
      ? `<div class="week-verdict"><span>本周判断</span><p>${esc(content.headline)}</p><a href="${path('advice')}">看依据 →</a></div>`
      : '';
    const metrics = availability.current
      ? `<div class="week-kpis">${[
          title('订单营业收入', wan(kpis.current_revenue), comparison),
          title('正向订单', integer(orders), '环比 ' + pct(change(orders, previousOrders))),
          title(
            '折后单均',
            money(ratio(kpis.current_revenue, orders)),
            '环比 ' +
              pct(change(ratio(kpis.current_revenue, orders), ratio(previousRevenue, previousOrders))),
          ),
          title(
            '外卖收入占比',
            deliveryShare === null ? '—' : num(deliveryShare * 100, 1) + '%',
            shareDifference === null
              ? ''
              : `较上周 ${shareDifference >= 0 ? '+' : ''}${num(shareDifference, 1)} 个百分点`,
          ),
        ].join('')}</div>`
      : '<p class="week-empty">本周暂无可用经营数据。</p>';
    shell(`<header class="week-title">${heading('周经营驾驶舱')}<span>${esc(meta.target_windows.current.start)} — ${esc(meta.target_windows.current.end)} · ${rows.length} 家门店</span></header>
   ${verdict}${metrics}<div class="week-charts">${charts.map((chart) => chartPanel(chart)).join('')}</div>${rows.length ? storeLinks() : ''}`);
    attachCharts(charts);
  }

  function store(index) {
    const row = rows[index];
    if (!row) return home();
    const name = row['门店名称'];
    const storeReview = advisory?.store_reviews.find((item) => item.store_name === name);
    const review = voice?.stores.find((item) => item.store_name === name);
    const sections = [
      [
        'meals',
        '餐段经营',
        details.meals?.some((item) => item['门店名称'] === name) ||
          storeReview?.meal_periods.status === 'supported',
      ],
      [
        'dishes',
        '菜品结构',
        details.products?.some((item) => item['门店名称'] === name) ||
          storeReview?.dishes.status === 'supported',
      ],
      [
        'stalls',
        '档口结构',
        details.stalls?.some((item) => item['门店名称'] === name) ||
          storeReview?.stalls.status === 'supported',
      ],
      [
        'channels',
        '堂食与外卖',
        Number.isFinite(row.current_dine_in_revenue) || Number.isFinite(row.current_delivery_revenue),
      ],
      ...(review ? [['voice', '顾客声音', true]] : []),
    ].filter(([, , available]) => available);
    shell(
      `${crumbs([['门店', path('stores')]])}${heading(name)}
   <div class="week-kpis">${[
     title('订单营业收入', wan(row.current_net_revenue), '环比 ' + pct(row.wow_net_revenue_pct)),
     title('正向订单', integer(row.current_positive_orders)),
     title('折后单均', money(row.current_post_discount_aov)),
   ].join('')}</div>
   ${storeReview ? `<div class="week-verdict"><span>本周判断</span><p>${esc(storeReview.meal_periods.judgment || storeReview.dishes.judgment || storeReview.stalls.judgment)}</p></div>` : ''}
   <div class="week-links">${sections.map(([id, label]) => link(id === 'voice' ? path('voice', index) : path('store', index, id), label)).join('')}</div>`,
      'store',
    );
  }

  function crumbs(parents = []) {
    return `<nav class="week-crumbs" aria-label="阅读路径"><a href="${path('home')}">总览</a>
   ${parents.map(([label, target]) => `<span aria-hidden="true"> / </span><a href="${target}">${esc(label)}</a>`).join('')}</nav>`;
  }

  /*__WEEKLY_DETAILS__*/

  function navigate() {
    const parts = location.hash.startsWith('#/weekly/')
      ? location.hash.slice(9).split('/').map(decodeURIComponent)
      : ['home'];
    const [page, arg, leaf, selectedItem] = parts;
    restore();
    if (page === 'stores') shell(crumbs() + heading('门店') + storeLinks(), 'stores');
    else if (page === 'store') leaf ? storeSection(Number(arg), leaf, selectedItem) : store(Number(arg));
    else if (page === 'advice') advice(arg);
    else if (page === 'voice' && voice) customerVoice(arg, leaf);
    else if (page === 'topics')
      shell(
        crumbs() +
          heading('跨店专题') +
          `<div class="week-links">${charts.map((chart) => link(path('chart', chart.id), chart.label)).join('')}</div>`,
        'topics',
      );
    else if (page === 'chart' && charts.some((chart) => chart.id === arg)) {
      const chart = charts.find((chart) => chart.id === arg);
      shell(crumbs([['跨店专题', path('topics')]]) + chartPanel(chart, true), 'chart');
      attachCharts([chart]);
    } else home();
    app.querySelector('h1')?.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }
  mobile.addEventListener('change', () => {
    drawer = false;
    syncNav();
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && drawer) closeDrawer();
  });
  addEventListener('hashchange', navigate);
  addEventListener('beforeprint', restore);
  addEventListener('afterprint', navigate);
  navigate();
})();
