import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const reportsDir = "D:\\AI\\Claude\\Y_BankAuto\\reports";

async function latestJson() {
  const files = await fs.readdir(reportsDir);
  const candidates = files
    .filter((name) => /^db_compare_clean_\d{8}_\d{6}\.json$/.test(name))
    .map((name) => path.join(reportsDir, name));
  if (!candidates.length) throw new Error("No db_compare JSON found");
  const stats = await Promise.all(candidates.map(async (file) => [file, (await fs.stat(file)).mtimeMs]));
  stats.sort((a, b) => b[1] - a[1]);
  return stats[0][0];
}

function toMatrix(rows, headers) {
  return [
    headers,
    ...rows.map((row) => headers.map((header) => row[header] ?? "")),
  ];
}

function columnLetter(index) {
  let n = index + 1;
  let s = "";
  while (n > 0) {
    const rem = (n - 1) % 26;
    s = String.fromCharCode(65 + rem) + s;
    n = Math.floor((n - 1) / 26);
  }
  return s;
}

function writeSheet(workbook, name, rows, headers, options = {}) {
  const sheet = workbook.worksheets.add(name);
  sheet.showGridLines = false;
  const data = toMatrix(rows, headers);
  const rowCount = Math.max(data.length, 1);
  const colCount = Math.max(headers.length, 1);
  const range = sheet.getRangeByIndexes(0, 0, rowCount, colCount);
  range.values = data;

  const headerRange = sheet.getRangeByIndexes(0, 0, 1, colCount);
  headerRange.format = {
    fill: options.headerFill ?? "#1F4E78",
    font: { bold: true, color: "#FFFFFF" },
    wrapText: true,
    borders: { preset: "all", style: "thin", color: "#BFBFBF" },
  };

  if (rowCount > 1) {
    const bodyRange = sheet.getRangeByIndexes(1, 0, rowCount - 1, colCount);
    bodyRange.format = {
      wrapText: true,
      borders: { preset: "all", style: "thin", color: "#D9E2F3" },
    };
  }

  sheet.freezePanes.freezeRows(1);
  const used = sheet.getRangeByIndexes(0, 0, rowCount, colCount);
  used.format.autofitColumns();
  used.format.autofitRows();

  for (let i = 0; i < colCount; i++) {
    const width = options.widths?.[headers[i]];
    if (width) sheet.getRangeByIndexes(0, i, rowCount, 1).format.columnWidthPx = width;
  }

  if (options.filter !== false && rowCount >= 2) {
    const lastCol = columnLetter(colCount - 1);
    const tableName = `${name.replace(/[^A-Za-z0-9_]/g, "_")}_Table`.slice(0, 80);
    try {
      sheet.tables.add(`A1:${lastCol}${rowCount}`, true, tableName);
    } catch {
      // Tables are a usability enhancement only; keep the workbook if table creation is unavailable.
    }
  }

  return sheet;
}

function sortedByCount(rows) {
  return [...rows].sort((a, b) => Number(b["DiffCount"] ?? 0) - Number(a["DiffCount"] ?? 0));
}

const inputJson = await latestJson();
const payload = JSON.parse(await fs.readFile(inputJson, "utf8"));
const created = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14);
const outputXlsx = path.join(reportsDir, `db_compare_report_${created}.xlsx`);

const workbook = Workbook.create();

const summaryRows = [
  ...payload.summary_metrics,
  { "Metric": "", "Value": "" },
  { "Metric": "TopMasterDiffFields", "Value": sortedByCount(payload.master_field_counts).slice(0, 8).map((r) => `${r["Field"]}:${r["DiffCount"]}`).join(", ") },
  { "Metric": "TopInventoryDiffFields", "Value": sortedByCount(payload.inventory_field_counts).slice(0, 8).map((r) => `${r["Field"]}:${r["DiffCount"]}`).join(", ") },
];

writeSheet(workbook, "Summary", summaryRows, ["Metric", "Value"], {
  widths: { "Metric": 260, "Value": 720 },
  filter: false,
});

writeSheet(
  workbook,
  "By CustDocID",
  payload.summary_by_doc,
  ["CustDocID", "BankCustomer", "Status", "MasterDiffCount", "InventoryDiffCount", "TestInvRows", "RealInvRows", "TestMasterID", "RealMasterID", "TestDocID", "RealDocID"],
  {
    widths: {
      "CustDocID": 150,
      "BankCustomer": 240,
      "Status": 120,
      "TestDocID": 150,
      "RealDocID": 150,
    },
  },
);

writeSheet(
  workbook,
  "Master Diff",
  payload.master_diffs,
  ["CustDocID", "BankCustomer", "Field", "TestValue", "RealValue", "TestMasterID", "RealMasterID", "TestDocID", "RealDocID"],
  {
    headerFill: "#7F1D1D",
    widths: {
      "CustDocID": 150,
      "BankCustomer": 220,
      "Field": 120,
      "TestValue": 360,
      "RealValue": 360,
    },
  },
);

writeSheet(
  workbook,
  "Inventory Diff",
  payload.inventory_diffs,
  ["CustDocID", "BankCustomer", "InventoryIndex", "Field", "TestValue", "RealValue", "TestMasterID", "RealMasterID", "TestDocID", "RealDocID"],
  {
    headerFill: "#7C2D12",
    widths: {
      "CustDocID": 150,
      "BankCustomer": 220,
      "Field": 100,
      "TestValue": 360,
      "RealValue": 360,
    },
  },
);

writeSheet(
  workbook,
  "Field Counts",
  [
    { "Area": "Master", "Field": "", "DiffCount": "" },
    ...sortedByCount(payload.master_field_counts).map((r) => ({ "Area": "Master", ...r })),
    { "Area": "Inventory", "Field": "", "DiffCount": "" },
    ...sortedByCount(payload.inventory_field_counts).map((r) => ({ "Area": "Inventory", ...r })),
  ],
  ["Area", "Field", "DiffCount"],
  { widths: { "Area": 120, "Field": 160, "DiffCount": 120 } },
);

writeSheet(
  workbook,
  "Missing Real",
  payload.missing_real,
  ["CustDocID", "TestMasterID", "TestDocID", "TestCustName", "TestTitle"],
  { widths: { "CustDocID": 150, "TestCustName": 240, "TestTitle": 360 } },
);

writeSheet(
  workbook,
  "Master Map",
  payload.master_raw_rows,
  ["CustDocID", "TestMasterID", "RealMasterID", "TestDocID", "RealDocID", "TestCustName", "RealCustName", "TestTitle", "RealTitle"],
  {
    widths: {
      "CustDocID": 150,
      "TestCustName": 240,
      "RealCustName": 240,
      "TestTitle": 360,
      "RealTitle": 360,
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

for (const sheetName of ["Summary", "By CustDocID", "Master Diff", "Inventory Diff"]) {
  const preview = await workbook.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
  const previewBytes = new Uint8Array(await preview.arrayBuffer());
  await fs.writeFile(path.join(reportsDir, `${sheetName}_${created}.png`), previewBytes);
}

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputXlsx);
console.log(outputXlsx);
