import ExcelJS from 'exceljs';

export type PhaseKey = 'step0' | 'step1' | 'step2' | 'step3';

interface PhaseDef {
  title: string;
  key: PhaseKey;
  columns: string[];
}

// (sheet title, results key, columns to keep in that order)
const PHASES: PhaseDef[] = [
  { title: 'Meter Coverage', key: 'step0', columns: ['Match Key', 'Value', 'Client Name', 'Issue'] },
  {
    title: 'Metadata',
    key: 'step1',
    columns: ['Meter Number', 'Client Name', 'Mismatched Field', 'Original Field (Hebrew)', 'Alteco Value', 'Client Value'],
  },
  {
    title: 'Consumption',
    key: 'step2',
    columns: ['Meter Number', 'Client Name', 'Mismatched Field', 'Original Field (Hebrew)', 'Alteco Value', 'Client Value'],
  },
  {
    title: 'Financial',
    key: 'step3',
    columns: ['Customer ID', 'Client Name', 'Mismatched Field', 'Original Field (Hebrew)', 'Alteco Value', 'Client Value'],
  },
];

const HEADER_FILL: ExcelJS.Fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF1F2937' } };
const HEADER_FONT: Partial<ExcelJS.Font> = { bold: true, color: { argb: 'FFFFFFFF' } };

function styleSheet(worksheet: ExcelJS.Worksheet, ncols: number): void {
  const headerRow = worksheet.getRow(1);
  for (let col = 1; col <= ncols; col++) {
    const cell = headerRow.getCell(col);
    cell.font = HEADER_FONT;
    cell.fill = HEADER_FILL;
  }
  worksheet.views = [{ state: 'frozen', ySplit: 1 }];
  worksheet.autoFilter = { from: { row: 1, column: 1 }, to: { row: 1, column: ncols } };

  for (let col = 1; col <= ncols; col++) {
    let maxLen = 10;
    for (let row = 1; row <= worksheet.rowCount; row++) {
      const value = worksheet.getRow(row).getCell(col).value;
      const len = value === null || value === undefined ? 0 : String(value).length;
      if (len > maxLen) maxLen = len;
    }
    worksheet.getColumn(col).width = Math.min(Math.max(maxLen + 2, 12), 60);
  }
}

/**
 * Builds a formatted .xlsx report from a reconciliation results object
 * ({step0: [...], step1: [...], step2: [...], step3: [...]}). Sheet order:
 * Summary first, then one sheet per phase (bold header row, frozen header,
 * auto-filter, auto-sized columns) -- empty phases still get a sheet, with a
 * clear "no discrepancies" note instead of being skipped. Returns a Buffer
 * ready to stream as a response body.
 */
export async function buildDiscrepancyWorkbook(results: Record<string, Array<Record<string, unknown>>>): Promise<Buffer> {
  const workbook = new ExcelJS.Workbook();

  const summarySheet = workbook.addWorksheet('Summary');
  summarySheet.addRow(['Phase', 'Mismatches']);
  for (const { title, key } of PHASES) {
    summarySheet.addRow([title, (results[key] ?? []).length]);
  }
  summarySheet.getCell('C1').value = 'Generated';
  summarySheet.getCell('C2').value = formatTimestamp(new Date());
  styleSheet(summarySheet, 2);

  for (const { title, key, columns } of PHASES) {
    const rows = results[key] ?? [];
    const worksheet = workbook.addWorksheet(title);
    if (rows.length > 0) {
      const presentColumns = columns.filter((c) => Object.prototype.hasOwnProperty.call(rows[0], c));
      worksheet.addRow(presentColumns);
      for (const row of rows) {
        worksheet.addRow(presentColumns.map((c) => row[c] ?? null));
      }
      styleSheet(worksheet, presentColumns.length);
    } else {
      worksheet.addRow(['Result']);
      worksheet.addRow(['No discrepancies found']);
      styleSheet(worksheet, 1);
    }
  }

  const arrayBuffer = await workbook.xlsx.writeBuffer();
  return Buffer.from(arrayBuffer);
}

function formatTimestamp(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
