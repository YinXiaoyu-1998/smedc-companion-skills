import fs from 'node:fs/promises';
import path from 'node:path';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const [recordsPath, outputPath, previewDir] = process.argv.slice(2);
if (!recordsPath || !outputPath || !previewDir) throw new Error('Usage: review_workbook.mjs RECORDS OUTPUT_XLSX PREVIEW_DIR');
await fs.access(outputPath).then(() => { throw new Error('Refusing to overwrite an existing workbook'); }, e => { if (e.code !== 'ENOENT') throw e; });
const records = JSON.parse(await fs.readFile(recordsPath, 'utf8'));
if (!Array.isArray(records)) throw new Error('records must be an array');
const header = ['客户名字','客户原评价','拟回复内容','用户评分','评价日期','门店名称','企业名称','渠道','回复状态'];
const reply = r => r.sheetStatus === '新生成待审核' ? r.draftReply : r.sheetStatus === '已回复' ? r.merchantReply : null;
const rows = records.map(r => {
  for (const key of ['reviewerName','storeName','enterpriseName','source','sheetStatus']) if (typeof r[key] !== 'string' || !r[key].trim()) throw new Error(`Missing ${key}`);
  if (r.sheetStatus === '新生成待审核' && (!r.content || !r.draftReply?.trim())) throw new Error('Draft lacks content/reply');
  if (r.sheetStatus === '已回复' && !r.merchantReply?.trim()) throw new Error('Replied row lacks complete reply');
  const score = r.scores?.['总评'] ?? null;
  if (score !== null && (typeof score !== 'number' || !Number.isFinite(score))) throw new Error('Score must be a finite number');
  let date = `待核对：${r.rawReviewedAt || '来源未显示时间'}`;
  if (r.reviewedAt) {
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+08:00$/.test(r.reviewedAt)) throw new Error('Expected canonical Beijing timestamp');
    date = new Date(r.reviewedAt.slice(0,19) + 'Z');
    if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0,19) !== r.reviewedAt.slice(0,19)) throw new Error('Invalid date');
    // Native Excel serial dates avoid sub-millisecond drift in the Date export path.
    date = date.getTime() / 86400000 + 25569;
  }
  return [r.reviewerName,r.content ?? null,reply(r) ?? null,score,date,r.storeName,r.enterpriseName,r.source,r.sheetStatus];
});
const wb = Workbook.create(), sheet = wb.worksheets.add('评价审阅表'), last = rows.length + 1;
const literal = value => typeof value === 'string' && value.startsWith('=') ? "'" + value : value;
sheet.getRange(`A1:I${last}`).values = [header,...rows.map(row => row.map(literal))];
sheet.showGridLines = false;
sheet.getRange(`A1:I${last}`).format = {font:{name:'Arial',size:11},verticalAlignment:'top',wrapText:true};
[22,66,82,12,32,25,15,14,29].forEach((w,i) => { sheet.getRange(`${String.fromCharCode(65+i)}1:${String.fromCharCode(65+i)}${last}`).format.columnWidth = w; });
sheet.getRange('A1:I1').format = {fill:'#293B4B',font:{name:'Arial',size:11,bold:true,color:'#FFFFFF'},rowHeight:30,horizontalAlignment:'center',verticalAlignment:'center'};
if (rows.length) {
  sheet.getRange(`D2:D${last}`).setNumberFormat('General');
  sheet.getRange(`E2:E${last}`).setNumberFormat('yyyy-mm-dd"T"hh:mm:ss"+08:00"');
}
const lines = (t,w) => String(t ?? '').split('\n').reduce((sum,l) => sum + Math.max(1,Math.ceil([...l].reduce((n,c) => n + (/[\u2E80-\uFFFF]/.test(c)?2:1),0)/(w-3))),0);
records.forEach((r,i) => { sheet.getRange(`A${i+2}:I${i+2}`).format.rowHeight = Math.max(90,15*Math.max(lines(r.content,66),lines(reply(r),82))+18); });
sheet.freezePanes.freezeRows(1); sheet.freezePanes.freezeColumns(1);
if (rows.length) sheet.tables.add(`A1:I${last}`,true,'ReviewTable').showFilterButton = true;
wb.recalculate();
await fs.mkdir(previewDir,{recursive:true});
const check = await wb.inspect({kind:'table',range:`评价审阅表!A1:I${last}`,include:'values,formulas',tableMaxRows:3,tableMaxCols:9,maxChars:1800});
await fs.writeFile(path.join(previewDir,'inspect.ndjson'),check.ndjson);
for (let first=1;first<=last;first+=10) {
  const blob=await wb.render({sheetName:'评价审阅表',range:`A${first}:I${Math.min(first+9,last)}`,scale:1,format:'png'});
  await fs.writeFile(path.join(previewDir,`preview-${first}.png`),new Uint8Array(await blob.arrayBuffer()));
}
await fs.mkdir(path.dirname(outputPath),{recursive:true});
await (await SpreadsheetFile.exportXlsx(wb)).save(outputPath);
console.log(JSON.stringify({workbook:outputPath,rows:records.length,previewDir}));
