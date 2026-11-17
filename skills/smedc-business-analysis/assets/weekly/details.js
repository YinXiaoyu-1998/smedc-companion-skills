const storeSections = {
  meals: ['餐段经营', '餐段', 'meals', 'meal_periods'],
  dishes: ['菜品结构', '原品项', 'products', 'dishes'],
  stalls: ['档口结构', '档口', 'stalls', 'stalls'],
  channels: ['堂食与外卖', '渠道', null, null],
};
const details = content.details;
function evidence(items) {
  return items.length
    ? `<details><summary>查看数值依据</summary><ul>${items
        .map(
          (item) =>
            `<li>${esc(item.label)} · ${esc(item.format === 'percent' ? num(Number(item.value) * 100, 2) + '%' : item.value)}</li>`,
        )
        .join('')}</ul></details>`
    : '';
}
const paragraph = (label, text) =>
  text ? `<div class="week-copy"><h2>${label}</h2><p>${esc(text)}</p></div>` : '';
const detailCard = (label, values) => `<article class="week-panel week-fact"><h3>${esc(label)}</h3>
  <dl>${values.map(([key, value]) => `<div><dt>${esc(key)}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl></article>`;
function storeSection(index, section, selectedItem) {
  const row = rows[index],
    config = storeSections[section];
  if (!row || !config) return home();
  const [label, itemLabel, dataset, analysisKey] = config;
  const name = row['门店名称'];
  const parent = [
    ['门店', path('stores')],
    [short(name), path('store', index)],
  ];
  const storeReview = advisory?.store_reviews.find((item) => item.store_name === name);
  const analysis = storeReview?.[analysisKey];
  if (section === 'channels') {
    const values = [
      ['堂食', row.current_dine_in_revenue, row.previous_dine_in_revenue],
      ['外卖', row.current_delivery_revenue, row.previous_delivery_revenue],
      ['美团外卖', row.current_meituan_delivery_revenue, row.previous_meituan_delivery_revenue],
      ['饿了么／淘宝闪购', row.current_eleme_delivery_revenue, row.previous_eleme_delivery_revenue],
      ['京东外卖', row.current_jd_delivery_revenue, row.previous_jd_delivery_revenue],
    ].filter(([, current, prior]) => Number.isFinite(current) || Number.isFinite(prior));
    shell(
      crumbs(parent) +
        heading(label) +
        `<div class="week-facts">${values
          .map(([name, current, prior]) =>
            detailCard(name, [
              ['本周', money(current)],
              ['上周', money(prior)],
              ['环比', pct(change(current, prior))],
            ]),
          )
          .join('')}</div>`,
      'store-section',
    );
    return;
  }
  const facts = details[dataset].filter((item) => item['门店名称'] === name);
  if (section === 'dishes') {
    const itemName = (item) => item['原始品项'] || item['产品名称'];
    const items = [...new Set(facts.map(itemName))];
    if (selectedItem != null && items.includes(selectedItem)) {
      const product = facts
        .filter((item) => itemName(item) === selectedItem)
        .sort((a, b) => a.period_key.localeCompare(b.period_key));
      shell(
        crumbs([...parent, [label, path('store', index, section)]]) +
          heading(selectedItem) +
          `<div class="week-facts">${product
            .map((item) =>
              detailCard((item['销售分类'] || '全渠道') + (item.record_kind === 'fee' ? ' · 收费项' : ''), [
                ['时期', item.period_key === 'current' ? '本周' : '上周'],
                ['销量（原品项单位）', num(item.quantity)],
                ['菜品收入', money(item.dish_income)],
                ...(Number.isFinite(item.units_per_10k)
                  ? [['每万元订单营业收入销量', num(item.units_per_10k)]]
                  : []),
                ...(item['档口'] && item['档口'] !== '未匹配' ? [['档口', item['档口']]] : []),
              ]),
            )
            .join('')}</div>`,
        'store-section',
      );
      return;
    }
    shell(
      crumbs(parent) +
        heading(label) +
        renderStoreAnalysis(analysis) +
        `<label class="week-search">${itemLabel}<input type="search" aria-label="搜索品项" placeholder="搜索品项"></label>
     <div id="week-product-list" class="week-links"></div>`,
      'store-section',
    );
    const input = app.querySelector('.week-search input');
    const paint = () => {
      const matched = items.filter((item) => item.includes(input.value.trim()));
      const visible = matched.slice(0, 60);
      const feeItems = new Set(facts.filter((item) => item.record_kind === 'fee').map(itemName));
      const itemsFor = (fee) => visible.filter((item) => feeItems.has(item) === fee);
      const productLinks = (subset) =>
        subset.map((item) => link(path('store', index, section, item), item)).join('');
      document.getElementById('week-product-list').innerHTML =
        productLinks(itemsFor(false)) +
        (itemsFor(true).length
          ? '<h2 class="week-links-heading">餐具与收费项</h2>' + productLinks(itemsFor(true))
          : '') +
        (matched.length > visible.length ? '<p>搜索可定位其余品项。</p>' : '') +
        (!matched.length ? '<p>暂无匹配品项。</p>' : '');
    };
    input.addEventListener('input', paint);
    paint();
    return;
  }
  shell(
    crumbs(parent) +
      heading(label) +
      renderStoreAnalysis(analysis) +
      `<div class="week-facts">${facts
        .map((item) =>
          detailCard(item['餐段'] || item['档口'] || '其他', [
            ['本周收入', money(item.current_net_revenue)],
            ['上周收入', money(item.previous_net_revenue)],
            ['环比', pct(change(item.current_net_revenue, item.previous_net_revenue))],
          ]),
        )
        .join('')}</div>`,
    'store-section',
  );
}
function renderStoreAnalysis(analysis) {
  if (!analysis || analysis.status !== 'supported') return '';
  return `<section class="week-panel">${paragraph('本期表现', analysis.observation)}
   ${paragraph('经营判断', analysis.judgment)}${paragraph('下一步', analysis.next_step)}${evidence(analysis.evidence)}</section>`;
}
function advice(index) {
  const items = advisory?.findings || [];
  const item = index == null ? null : items[Number(index)];
  if (item) {
    const action = item.action;
    shell(
      crumbs([['经营建议', path('advice')]]) +
        heading(item.title) +
        paragraph('经营判断', item.interpretation) +
        paragraph('本期表现', item.observation) +
        paragraph('可能原因', item.hypothesis) +
        paragraph('其他可能', item.alternative) +
        paragraph('补充说明', item.caveat) +
        `<section class="week-panel"><h2>行动与复盘</h2><p>${esc(action.owner_role)} · ${esc(action.scope)}</p>
     <ol>${action.steps.map((step) => `<li>${esc(step)}</li>`).join('')}</ol>
     ${detailCard('复盘标准', [
       ['复盘时间', action.review_after],
       ['主观察指标', action.primary_metric],
       ['同时观察', action.guardrail],
       ['调整条件', action.stop_rule],
     ])}
    </section>` +
        evidence(item.evidence),
      'advice',
    );
    return;
  }
  shell(
    crumbs() +
      heading('本周经营建议') +
      (items.length
        ? `<div class="week-links">${items.map((item, i) => link(path('advice', i), item.title)).join('')}</div>`
        : '<p>本期暂无企业层面的优先建议。逐店分析可从门店查看。</p>') +
      (advisory?.management_questions.length
        ? `<section class="week-panel"><h2>下次经营会</h2><ul>${advisory.management_questions
            .map((item) => `<li>${esc(item.question)} · ${esc(item.decision_impact)}</li>`)
            .join('')}</ul></section>`
        : '') +
      (voice ? link(path('voice'), '顾客声音') : ''),
    'advice',
  );
}
function customerVoice(index, themeIndex) {
  const entry =
    index == null ? null : voice.stores.find((item) => item.store_name === rows[Number(index)]?.['门店名称']);
  const theme = entry && themeIndex != null ? entry.themes[Number(themeIndex)] : null;
  const parent = [['顾客声音', path('voice')]];
  if (theme) {
    shell(
      crumbs([...parent, [short(entry.store_name), path('voice', index)]]) +
        heading(theme.title) +
        paragraph('经营判断', theme.judgment) +
        paragraph('观察', theme.observation) +
        paragraph('下一步', theme.action) +
        `<details><summary>查看引用依据</summary>${theme.evidence
          .map(
            (item) =>
              `<figure><figcaption>${esc(item.source)} · ${esc(item.date)}</figcaption><blockquote>${esc(item.excerpt)}</blockquote></figure>`,
          )
          .join('')}</details>`,
      'voice',
    );
  } else if (entry) {
    shell(
      crumbs(parent) +
        heading(entry.store_name) +
        paragraph('本周判断', entry.headline) +
        `<div class="week-cloud" aria-label="本周评价主题">${entry.themes.map((item, i) => `<a data-tone="${item.tone}" href="${path('voice', index, i)}">${esc(item.cloud_label)}</a>`).join('')}</div>` +
        `<div class="week-facts">${[
          ['keep', '值得保持'],
          ['check', '优先核查'],
        ]
          .map(
            ([tone, label]) =>
              `<section class="week-panel"><h2>${label}</h2>${
                entry.themes
                  .filter((item) => item.tone === tone)
                  .map((item) => link(path('voice', index, entry.themes.indexOf(item)), item.title))
                  .join('') || '<p>本期无明确主题。</p>'
              }</section>`,
          )
          .join('')}</div>`,
      'voice',
    );
  } else {
    shell(
      crumbs() +
        heading('顾客声音') +
        paragraph('本周判断', voice.overview) +
        `<div class="week-links">${voice.stores
          .map((item) =>
            link(
              path(
                'voice',
                rows.findIndex((row) => row['门店名称'] === item.store_name),
              ),
              short(item.store_name) + ' · ' + item.headline,
            ),
          )
          .join('')}</div>`,
      'voice',
    );
  }
}
