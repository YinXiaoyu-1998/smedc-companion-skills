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
function dashboardRank(width) {
  const left = 86;
  const right = 53;
  const rowHeight = 23;
  const barHeight = 13;
  const plotWidth = width - left - right;
  const maximum = Math.max(1, ...rows.map((row) => row.current_net_revenue));
  let body = '';
  let y = 22;

  for (const group of groups) {
    body += svgText(3, y - 7, group.label, 'class="dash-group-label"');
    body += svgText(
      width - 3,
      y - 7,
      `中位数 ${num(group.revenue_threshold / 10000, 1)}万`,
      'text-anchor="end" class="dash-small"',
    );
    const stores = rows
      .map((row, index) => ({ row, index }))
      .filter(({ row }) => row.store_size === group.key)
      .sort((a, b) => b.row.current_net_revenue - a.row.current_net_revenue);

    for (const { row, index } of stores) {
      const total = row.current_net_revenue;
      const dineIn = row.current_dine_in_revenue;
      const delivery = row.current_delivery_revenue;
      const other = Number.isFinite(dineIn) && Number.isFinite(delivery) ? total - dineIn - delivery : 0;
      let x = left;
      let mark = svgText(left - 8, y + 12, short(row['门店名称']), 'text-anchor="end"');
      for (const [label, value, color] of [
        ['堂食', dineIn, palette.teal],
        ['外卖', delivery, palette.blue],
        ['其他', other, palette.gold],
        [
          '结构未覆盖',
          !Number.isFinite(dineIn) || !Number.isFinite(delivery)
            ? total - (dineIn ?? 0) - (delivery ?? 0)
            : 0,
          '#a1ada6',
        ],
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
  const h = groups.length * 130 + 3,
    left = 32,
    right = 12,
    plotW = w - left - right;
  let body = '';
  groups.forEach((group, g) => {
    const top = 20 + g * 130,
      plotH = 94;
    const selected = rows
      .map((r, i) => ({ r, i }))
      .filter((x) => x.r.store_size === group.key && Number.isFinite(x.r.wow_net_revenue_pct));
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
    ['饿了么／淘宝闪购', 'current_eleme_delivery_revenue', palette.purple],
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
    mark += svgText(
      x + 5,
      y + 12,
      series.every(([, key]) => row[key] == null) ? '—' : num(totals[index] / 10000, 1) + '万',
      'class="dash-value"',
    );
    body += chartLink(index, `${row['门店名称']}，外卖平台收入合计 ${num(totals[index])} 元`, mark);
  });
  return svgRoot(width, rows.length * rowHeight + 9, '外卖平台收入', body);
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
    max = Math.ceil(Math.max(1, ...rs.map((r) => r.net_revenue)) / 50000) * 50000;
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
