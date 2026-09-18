import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const reportsDir = "D:\\AI\\Claude\\Y_BankAuto\\reports";

async function latestPayload() {
  const files = await fs.readdir(reportsDir);
  const candidates = files
    .filter((name) => /^server_excel_vs_testdb_\d{8}_\d{6}\.json$/.test(name))
    .map((name) => path.join(reportsDir, name));
  if (!candidates.length) throw new Error("No server_excel_vs_testdb JSON found");
  const stats = await Promise.all(candidates.map(async (file) => [file, (await fs.stat(file)).mtimeMs]));
  stats.sort((a, b) => b[1] - a[1]);
  const file = stats[0][0];
  return { file, payload: JSON.parse(await fs.readFile(file, "utf8")) };
}

function columnLetter(index) {
  let n = index + 1;
  let out = "";
  while (n > 0) {
    const rem = (n - 1) % 26;
    out = String.fromCharCode(65 + rem) + out;
    n = Math.floor((n - 1) / 26);
  }
  return out;
}

function matrix(rows, headers) {
  return [headers, ...rows.map((row) => headers.map((h) => row[h] ?? ""))];
}

function writeSheet(workbook, name, rows, headers, options = {}) {
  const sheet = workbook.worksheets.add(name);
  sheet.showGridLines = false;
  const values = matrix(rows, headers);
  const rowCount = Math.max(values.length, 1);
  const colCount = Math.max(headers.length, 1);
  const range = sheet.getRangeByIndexes(0, 0, rowCount, colCount);
  range.values = values;

  sheet.getRangeByIndexes(0, 0, 1, colCount).format = {
    fill: options.headerFill ?? "#1F4E78",
    font: { bold: true, color: "#FFFFFF" },
    wrapText: true,
    borders: { preset: "all", style: "thin", color: "#BFBFBF" },
  };
  if (rowCount > 1) {
    sheet.getRangeByIndexes(1, 0, rowCount - 1, colCount).format = {
      wrapText: true,
      borders: { preset: "all", style: "thin", color: "#D9E2F3" },
    };
  }
  sheet.freezePanes.freezeRows(1);
  range.format.autofitColumns();
  range.format.autofitRows();
  for (let i = 0; i < headers.length; i++) {
    const width = options.widths?.[headers[i]];
    if (width) sheet.getRangeByIndexes(0, i, rowCount, 1).format.columnWidthPx = width;
  }
  if (rowCount >= 2 && options.table !== false) {
    const lastCol = columnLetter(colCount - 1);
    const tableName = `${name.replace(/[^A-Za-z0-9_]/g, "_")}_Table`.slice(0, 80);
    try {
      sheet.tables.add(`A1:${lastCol}${rowCount}`, true, tableName);
    } catch {
      // Keep workbook usable even if table creation is unavailable.
    }
  }
  return sheet;
}

function sortByCount(rows) {
  return [...rows].sort((a, b) => Number(b.DiffCount ?? 0) - Number(a.DiffCount ?? 0));
}

const { file: inputJson, payload } = await latestPayload();
const stamp = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14);
const outputXlsx = path.join(reportsDir, `server_excel_vs_testdb_report_${stamp}.xlsx`);

const workbook = Workbook.create();

const summaryRows = [
  { Metric: "SourceExcel", Value: "D:\\AI\\Claude\\Y_BankAuto\\server Excel file provided by user" },
  { Metric: "InputJson", Value: inputJson },
  { Metric: "TestQuery", Value: payload.test_query },
  ...payload.summary_metrics,
  { Metric: "", Value: "" },
  { Metric: "TopDiffFields", Value: sortByCount(payload.field_counts).slice(0, 12).map((r) => `${r.Field}:${r.DiffCount}`).join(", ") },
];

writeSheet(workbook, "Summary", summaryRows, ["Metric", "Value"], {
  widths: { Metric: 260, Value: 760 },
  table: false,
});

writeSheet(
  workbook,
  "By CustDocID",
  payload.summary_by_doc,
  ["CustDocID", "Status", "ServerRows", "TestRows", "ComparedPairs", "DiffCount"],
  {
    widths: { CustDocID: 180, Status: 100 },
  },
);

writeSheet(
  workbook,
  "Column Diffs",
  payload.diff_rows,
  ["CustDocID", "PairIndex", "Field", "ServerValue", "TestValue", "ServerSheet", "ServerRow"],
  {
    headerFill: "#7F1D1D",
    widths: {
      CustDocID: 180,
      Field: 120,
      ServerValue: 360,
      TestValue: 360,
    },
  },
);

writeSheet(
  workbook,
  "Field Counts",
  sortByCount(payload.field_counts),
  ["Field", "DiffCount"],
  { widths: { Field: 160, DiffCount: 120 } },
);

writeSheet(
  workbook,
  "Server Only",
  payload.server_only_docs,
  ["CustDocID", "Reason"],
  { widths: { CustDocID: 180, Reason: 420 } },
);

writeSheet(
  workbook,
  "Skipped Test Only",
  payload.test_only_docs_skipped,
  ["CustDocID", "Reason"],
  { widths: { CustDocID: 180, Reason: 520 } },
);

writeSheet(
  workbook,
  "Excel ID Issues",
  [
    ...payload.excel_precision_notes.map((r) => ({ Type: "PrecisionNote", ...r })),
    ...payload.unmatchable_excel.map((r) => ({ Type: "Unmatchable", ...r })),
  ],
  ["Type", "Sheet", "Row", "ExcelCustDocID", "RecoveredDigits", "MatchPrefix", "CandidateCount", "Candidates", "Reason", "Note"],
  {
    headerFill: "#7C2D12",
    widths: {
      Type: 120,
      ExcelCustDocID: 180,
      RecoveredDigits: 180,
      Candidates: 360,
      Reason: 420,
      Note: 420,
    },
  },
);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 100 },
  summary: "formula error scan",
});
console.log(errors.ndjson);

for (const sheetName of ["Summary", "By CustDocID", "Column Diffs", "Field Counts"]) {
  const preview = await workbook.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(reportsDir, `${sheetName}_${stamp}.png`), new Uint8Array(await preview.arrayBuffer()));
}

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputXlsx);
console.log(outputXlsx);
