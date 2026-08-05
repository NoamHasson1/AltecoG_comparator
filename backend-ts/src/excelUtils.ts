import ExcelJS from 'exceljs';

export type ExcelRow = Record<string, unknown>;

export async function readWorkbook(source: string | Buffer): Promise<ExcelJS.Workbook> {
  const workbook = new ExcelJS.Workbook();
  if (typeof source === 'string') {
    await workbook.xlsx.readFile(source);
  } else {
    // exceljs's bundled .d.ts declares its own global `Buffer extends ArrayBuffer`,
    // which merges with (and corrupts) Node's real Buffer type -- a known bug in
    // their shipped types, not a real runtime mismatch, hence the `any` here.
    await workbook.xlsx.load(source as any); // eslint-disable-line @typescript-eslint/no-explicit-any
  }
  return workbook;
}

/** Unwraps exceljs's richer cell-value shapes (formulas, rich text, hyperlinks,
 * errors) down to a plain value -- matching what pandas' read_excel already
 * hands you directly for each of these cell kinds. */
function cellToPlainValue(raw: unknown): unknown {
  if (raw === null || raw === undefined) return null;
  if (raw instanceof Date) return raw;
  if (typeof raw === 'object') {
    const obj = raw as Record<string, unknown>;
    if ('richText' in obj) {
      const parts = obj.richText as Array<{ text: string }>;
      return parts.map((p) => p.text).join('');
    }
    if ('error' in obj) return null; // #N/A, #REF!, etc.
    if ('result' in obj) return cellToPlainValue(obj.result); // formula cell
    if ('text' in obj) return obj.text; // hyperlink cell {text, hyperlink}
  }
  return raw;
}

/** Row 1's cell values as trimmed strings, 1-indexed (headers[0] is unused,
 * matching exceljs's own 1-indexed row.values convention) so header text can
 * be looked up by the same column number used elsewhere. */
export function getHeaders(worksheet: ExcelJS.Worksheet): string[] {
  const headerRow = worksheet.getRow(1);
  const headers: string[] = [];
  headerRow.eachCell({ includeEmpty: true }, (cell, colNumber) => {
    const value = cellToPlainValue(cell.value);
    headers[colNumber] = value === null ? '' : String(value).trim();
  });
  return headers;
}

/** Every data row (everything below row 1) as a plain object keyed by header
 * text, one entry per row -- the row-oriented equivalent of a pandas
 * DataFrame's records, which is the natural shape to work with here since
 * the rest of the app already deals in arrays of row objects at its edges.
 *
 * `maxRows` bounds how many data rows get materialized -- important for
 * something like a mapping-preview endpoint that only ever shows the first
 * few rows: a real ~70k-row sheet with 100+ columns is multiple GB of JS
 * objects if built in full just to immediately slice(0, 3) off the front. */
export function sheetToRecords(
  worksheet: ExcelJS.Worksheet,
  headers: string[] = getHeaders(worksheet),
  maxRows?: number
): ExcelRow[] {
  const records: ExcelRow[] = [];
  const rowCount = worksheet.rowCount;
  for (let rowNumber = 2; rowNumber <= rowCount; rowNumber++) {
    if (maxRows !== undefined && records.length >= maxRows) break;
    const row = worksheet.getRow(rowNumber);
    const record: ExcelRow = {};
    let hasValue = false;
    for (let col = 1; col < headers.length; col++) {
      const header = headers[col];
      if (!header) continue;
      const value = cellToPlainValue(row.getCell(col).value);
      record[header] = value;
      if (value !== null && value !== '') hasValue = true;
    }
    // Skip a genuinely blank row -- real-world Excel files very commonly
    // have formatting (column-wide styles, leftover formatting from a
    // copy/paste) applied far past the actual data, which inflates
    // worksheet.rowCount well beyond the real row count. pandas' read_excel
    // trims these automatically; exceljs's rowCount does not, so without
    // this check a file like that produces thousands of phantom all-null
    // records that show up as false "missing from X" coverage gaps.
    if (!hasValue) continue;
    records.push(record);
  }
  return records;
}
