import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [payloadPath, outputPath, snapshotPath] = process.argv.slice(2);
if (!payloadPath || !outputPath || !snapshotPath) throw new Error("Missing input or output path");
const data = JSON.parse(await fs.readFile(payloadPath, "utf8"));
const workbook = Workbook.create();
const summary = workbook.worksheets.add("企业汇总");
const qualificationDetails = workbook.worksheets.add("荣誉与证书明细");
const changes = workbook.worksheets.add("本次变化");
const issues = workbook.worksheets.add("待核查");
const sources = workbook.worksheets.add("来源与说明");
for (const sheet of [summary, qualificationDetails, changes, issues, sources]) sheet.showGridLines = false;
summary.tabColor = "#24415C";
qualificationDetails.tabColor = "#4B6A85";
changes.tabColor = "#4B6A85";

const baseFont = { name: "Arial", size: 10, color: "#243447" };
const titleFont = { name: "Arial", size: 15, bold: true, color: "#1D3553" };
const header = { fill: "#24415C", font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" }, rowHeight: 32, verticalAlignment: "center", horizontalAlignment: "center", wrapText: true };

function columnName(index) {
  let result = "";
  for (let n = index; n > 0; n = Math.floor((n - 1) / 26)) result = String.fromCharCode(65 + (n - 1) % 26) + result;
  return result;
}

function title(sheet, text, note, lastColumn) {
  sheet.getRange(`A2:${lastColumn}2`).format.rowHeight = 28;
  sheet.getRange("A2").values = [[text]];
  sheet.getRange("A2").format.font = titleFont;
  sheet.getRange("A3").values = [[note]];
  sheet.getRange("A3").format.font = { ...baseFont, italic: true, color: "#5B6E7D" };
}

function table(sheet, columns, rows, widths = {}) {
  const last = columnName(columns.length);
  sheet.getRange(`A4:${last}4`).values = [columns];
  sheet.getRange(`A4:${last}4`).format = header;
  if (rows.length) {
    sheet.getRange(`A5:${last}${rows.length + 4}`).values = rows;
    sheet.getRange(`A5:${last}${rows.length + 4}`).format.font = baseFont;
    sheet.getRange(`A5:${last}${rows.length + 4}`).format.rowHeight = 21;
    sheet.getRange(`A5:${last}${rows.length + 4}`).format.verticalAlignment = "center";
  }
  for (let i = 0; i < columns.length; i++) {
    const col = columnName(i + 1);
    sheet.getRange(`${col}1:${col}${Math.max(rows.length + 4, 17)}`).format.columnWidth = widths[col] ?? 14;
  }
  sheet.freezePanes.freezeRows(4);
}

const years = data.years;
title(summary, "客户企业信息与资质汇总", `本地刷新日：${data.as_of}；专利按授权公告年度，软著按登记年度；数字仅表示所放导出文件的记录数。`, "A");
const summaryColumns = ["统一社会信用代码", "企业名称", "工商登记状态", "所在区县"];
for (const y of years) summaryColumns.push(`${y}发明授权`, `${y}实用新型授权`, `${y}软著登记`);
summaryColumns.push("近三年发明授权", "近三年实用新型授权", "近三年软著登记", "最近高企认定年", "最近专精特新认定年", "最近小巨人认定年", "有效证书记录", "荣誉记录", "现行标准记录", "注册商标记录", "新增记录", "信息变化", "本次未出现", "更新提示");
const summaryRows = data.summary.map((r) => [...r.slice(0, 13), null, null, null, ...r.slice(13), null]);
table(summary, summaryColumns, summaryRows, { A: 23, B: 34, C: 16, D: 13 });
summary.getRange(`E1:Z${summaryRows.length + 4}`).format.columnWidth = 15;
summary.getRange(`AA1:AA${summaryRows.length + 4}`).format.columnWidth = 22;
if (summaryRows.length) {
  const totals = summaryRows.map((_, i) => {
    const n = i + 5;
    return [`=SUM(E${n},H${n},K${n})`, `=SUM(F${n},I${n},L${n})`, `=SUM(G${n},J${n},M${n})`];
  });
  summary.getRange(`N5:P${summaryRows.length + 4}`).formulas = totals;
  if (data.first_run) {
    summary.getRange(`AA5:AA${summaryRows.length + 4}`).values = summaryRows.map(() => ["首次建档，暂无对比"]);
  } else {
    summary.getRange(`AA5:AA${summaryRows.length + 4}`).formulas = summaryRows.map((_, i) => {
      const n = i + 5;
      return [`=IF(Z${n}>0,"有记录未出现，需核查",IF(X${n}+Y${n}>0,"有新增或变化","本次无变化"))`];
    });
  }
  summary.getRange(`A5:A${summaryRows.length + 4}`).setNumberFormat("@");
  summary.getRange(`E5:P${summaryRows.length + 4}`).setNumberFormat("#,##0");
  summary.getRange(`Q5:S${summaryRows.length + 4}`).setNumberFormat("0");
  summary.getRange(`T5:Z${summaryRows.length + 4}`).setNumberFormat("#,##0");
  summary.getRange(`AA5:AA${summaryRows.length + 4}`).conditionalFormats.add("containsText", { text: "需核查", format: { fill: "#FBE2DE", font: { color: "#9A3027", bold: true } } });
}

title(qualificationDetails, "荣誉与证书明细", "保留每条导出记录与来源序号；荣誉级别不是有效状态，证书状态以本次导出为准。", "A");
const details = data.qualification_details.map((r) => r.map((value, index) => {
  if ((index === 6 || index === 7) && /^\d{4}-\d{2}-\d{2}$/.test(value)) return new Date(`${value}T00:00:00Z`);
  return value;
}));
table(qualificationDetails, ["统一社会信用代码", "企业名称", "类别", "名称", "编号", "状态或级别", "发证/发布日期", "有效期至", "导出记录序号"], details,
  { A: 23, B: 35, C: 15, D: 42, E: 27, F: 20, G: 19, H: 17, I: 18 });
if (details.length) {
  qualificationDetails.getRange(`A5:A${details.length + 4}`).setNumberFormat("@");
  qualificationDetails.getRange(`E5:E${details.length + 4}`).setNumberFormat("@");
  qualificationDetails.getRange(`G5:H${details.length + 4}`).setNumberFormat("yyyy-mm-dd");
  qualificationDetails.tables.add(`A4:I${details.length + 4}`, true, "QualificationDetails");
}

title(changes, "与上次导出相比", data.first_run ? "首次建档：下次替换七类导出后刷新，才会出现增量。" : `上次成功刷新：${data.previous_as_of || "日期未记录"}；本次刷新：${data.as_of}。`, "A");
table(changes, ["企业名称", "类别", "变化类型", "记录名称", "状态或变化", "本次导出序号"], data.changes, { A: 34, B: 15, C: 20, D: 48, E: 38, F: 18 });

title(issues, "需要人工核查的记录", "同编号不同内容已分别保留；请核对原导出，不能把冲突当作已确认的当前资质。", "A");
table(issues, ["类别", "企业名称", "问题", "导出记录序号"], data.problems, { A: 17, B: 36, C: 48, D: 20 });

title(sources, "来源与刷新说明", "只读取本地企查查导出；没有实时联网更新，也不自动确认资质有效性。", "A");
table(sources, ["类别", "源文件（相对项目目录）", "字节数", "SHA-256", "本次去重记录", "重复编号"], data.sources, { A: 17, B: 85, C: 15, D: 72, E: 19, F: 15 });
const instructions = [
  "使用方法：用新下载的同类文件替换“客户信息”中的旧导出；每类必须恰好一份；双击项目根目录的“刷新客户信息汇总.cmd”。",
  "更新口径：发明授权只计“发明授权”记录，实用新型计“实用新型”记录；不计发明公布和外观设计。已终止专利仍属于历史授权，法律状态须回看源文件。",
  "软著按登记日期计数；荣誉显示最近认定年份，不能据此推断当前有效。有效证书按导出状态“有效”且未过期计数。",
  "“本次未出现”不等于证书/权利已失效，可能是导出范围变化；应核查后再判断。原始导出和摘要校验码保留来源链。",
];
sources.getRange("A14:A17").values = instructions.map((x) => [x]);
sources.getRange("A14:A17").format.font = { ...baseFont, color: "#4A5B67" };
sources.getRange("A14:A17").format.rowHeight = 25;

await fs.mkdir(path.dirname(outputPath), { recursive: true });
workbook.recalculate();
for (const [sheet, range] of [["企业汇总", "A2:Q9"], ["荣誉与证书明细", "A2:I10"], ["本次变化", "A2:F8"], ["待核查", "A2:D10"], ["来源与说明", "A2:F17"]]) {
  const inspected = await workbook.inspect({ kind: "table", range: `${sheet}!${range}`, include: "values,formulas", tableMaxRows: 9, tableMaxCols: 17, maxChars: 3500 });
  console.log(sheet, inspected.ndjson.slice(0, 3500));
  const preview = await workbook.render({ sheetName: sheet, range, scale: 1.2, format: "png" });
  await fs.writeFile(path.join(path.dirname(outputPath), `${sheet}.png`), new Uint8Array(await preview.arrayBuffer()));
}
const summaryTail = await workbook.render({ sheetName: "企业汇总", range: "Q4:AA9", scale: 1.2, format: "png" });
await fs.writeFile(path.join(path.dirname(outputPath), "企业汇总_资质与变化.png"), new Uint8Array(await summaryTail.arrayBuffer()));
const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 50 }, summary: "final formula error scan" });
console.log("formula_errors", errors.ndjson.slice(0, 2000));
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
await fs.writeFile(snapshotPath, JSON.stringify(data.snapshot), "utf8");
console.log(`Saved ${outputPath}`);
