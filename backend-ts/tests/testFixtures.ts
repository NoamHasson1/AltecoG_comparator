import ExcelJS from 'exceljs';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

/** Writes a workbook with one sheet per entry in `sheets` ({name, rows}),
 * mirroring the pattern the Python tests use with pd.ExcelWriter. Returns
 * the temp file path; caller is responsible for deleting it (see the
 * `tempFile` helper below for automatic cleanup via afterEach). */
export async function writeWorkbook(sheets: Array<{ name: string; rows: Array<Record<string, unknown>> }>): Promise<string> {
  const workbook = new ExcelJS.Workbook();
  for (const { name, rows } of sheets) {
    const worksheet = workbook.addWorksheet(name);
    const headers = rows.length > 0 ? Object.keys(rows[0]) : [];
    worksheet.addRow(headers);
    for (const row of rows) {
      worksheet.addRow(headers.map((h) => row[h] ?? null));
    }
  }
  const filePath = path.join(os.tmpdir(), `fixture-${Date.now()}-${Math.random().toString(36).slice(2)}.xlsx`);
  await workbook.xlsx.writeFile(filePath);
  return filePath;
}

export function trackTempFiles() {
  const files: string[] = [];
  return {
    track(filePath: string) {
      files.push(filePath);
      return filePath;
    },
    cleanup() {
      for (const f of files.splice(0)) {
        if (fs.existsSync(f)) fs.unlinkSync(f);
      }
    },
  };
}
