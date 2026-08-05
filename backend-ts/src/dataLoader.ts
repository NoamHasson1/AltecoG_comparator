import { getHeaders, readWorkbook, sheetToRecords } from './excelUtils.js';
import { createLogger } from './logger.js';

const logger = createLogger('dataLoader');

// The unified schema both systems (Alteco and the client) get mapped to.
export const STANDARD_SCHEMA = [
  // Metadata
  'billing_month',
  'customer_id',
  'customer_name',
  'tax_id',
  'iec_contract',
  'meter_number',
  'voltage',
  'tou',
  'billing_type',
  'tariff',
  'fixed_payment',
  'contract_start_date',
  'kva',

  // Consumption
  'total_kwh',

  // Financials
  'total_payment',
  'kva_fixed_charge',
  'supply_fixed_charge',
  'distribution_fixed_charge',
] as const;

export type StandardField = (typeof STANDARD_SCHEMA)[number];
export type StandardRow = Record<StandardField, unknown>;

/**
 * Cleans a single identifier value read from Excel. In pandas, a blank cell
 * anywhere in an otherwise-integer ID column forces the whole column to
 * float64 (pandas can't represent NaN as int64), so "377007686" round-trips
 * as 377007686.0 and a naive str() would stringify it as "377007686.0" --
 * that specific artifact doesn't exist here since exceljs reads cell-by-cell
 * rather than column-wise, but this still normalizes blanks to null (not the
 * literal string "null"/"undefined") and trims whitespace, matching the
 * Python version's contract for every other case.
 */
export function normalizeIdValue(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === 'number' && Number.isNaN(value)) return null;
  if (value instanceof Date) return value.toISOString();
  return String(value).trim();
}

const RENAME_MAP: Record<string, StandardField> = {
  'חודש חיוב': 'billing_month',
  'מספר לקוח': 'customer_id',
  'שם לקוח': 'customer_name',
  'ח.פ לקוח': 'tax_id',
  'מספר חוזה חח״י': 'iec_contract',
  'מספר מונה': 'meter_number',
  מתח: 'voltage',
  'תעו״ז': 'tou',
  'סוג חיוב': 'billing_type',
  תעריף: 'tariff',
  'תשלום קבוע': 'fixed_payment',
  'תאריך התחלת החוזה': 'contract_start_date',
  KVA: 'kva',
  'סה״כ צריכה קוט״ש': 'total_kwh',
  'סה״כ לתשלום (כולל מע״מ) ₪': 'total_payment',
  'חיוב קבוע KVA ₪': 'kva_fixed_charge',
  'חיוב קבוע אספקה ₪': 'supply_fixed_charge',
  'חיוב קבוע חלוקה ₪': 'distribution_fixed_charge',
};

export async function loadAltecoData(source: string | Buffer): Promise<StandardRow[]> {
  logger.info(`ALTECO LOAD: reading sheet 'חשבונית חוזה'`);
  const workbook = await readWorkbook(source);
  const worksheet = workbook.getWorksheet('חשבונית חוזה');
  if (!worksheet) {
    throw new Error("Sheet 'חשבונית חוזה' not found in the uploaded Alteco file.");
  }

  const headers = getHeaders(worksheet);
  const headerSet = new Set(headers.filter(Boolean));
  logger.info(`ALTECO LOAD: read ${worksheet.rowCount - 1} rows, ${headerSet.size} columns`);

  // Loudly flag any expected Alteco column that wasn't found in the actual
  // header row -- a rename-map mismatch (e.g. a stray extra space in the
  // real file's header) would otherwise leave that field silently all-null
  // with no indication anything was wrong. This is exactly the class of bug
  // that once made Supply Fixed Charge look like it was always 0.
  for (const [hebrewCol, target] of Object.entries(RENAME_MAP)) {
    if (!headerSet.has(hebrewCol)) {
      logger.warn(
        `ALTECO COLUMN NOT FOUND: expected a column named exactly "${hebrewCol}" for '${target}', ` +
          'but no such column exists in the uploaded file. This field will be entirely blank in the ' +
          "results -- check for a spelling or spacing difference in the Alteco export's header."
      );
    }
  }

  const rawRecords = sheetToRecords(worksheet, headers);

  const result: StandardRow[] = rawRecords.map((raw) => {
    const row = Object.fromEntries(STANDARD_SCHEMA.map((field) => [field, null])) as StandardRow;
    for (const [hebrewCol, target] of Object.entries(RENAME_MAP)) {
      if (hebrewCol in raw) {
        row[target] = raw[hebrewCol];
      }
    }
    row.meter_number = normalizeIdValue(row.meter_number);
    row.customer_id = normalizeIdValue(row.customer_id);
    return row;
  });

  logger.debug(`ALTECO LOAD: final rows (${result.length}):`, JSON.stringify(result));
  return result;
}
