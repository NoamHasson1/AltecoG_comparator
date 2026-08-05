import { ExcelRow, getHeaders, readWorkbook, sheetToRecords } from './excelUtils.js';
import { STANDARD_SCHEMA, StandardRow, normalizeIdValue } from './dataLoader.js';
import { createLogger } from './logger.js';

const logger = createLogger('dynamicLoader');

export interface FieldMappingEntry {
  sheet: string;
  column: string;
}

export interface BillingMonthConfig {
  sheet: string;
  column: string;
  mode?: 'direct' | 'derive_from_date';
}

export interface LineItemsConfig {
  sheet: string;
  group_by_column: string;
}

export interface FilterConfig {
  column: string;
  match_type: 'equals' | 'contains_any';
  values: string[];
}

export interface CalculatedFieldRule {
  sheet: string;
  group_by_column: string;
  value_column: string;
  filters?: FilterConfig[];
}

export interface MappingConfig {
  field_mappings: Record<string, FieldMappingEntry>;
  billing_month?: BillingMonthConfig;
  line_items?: LineItemsConfig;
  calculated_fields?: Record<string, CalculatedFieldRule>;
}

export interface InspectedSheet {
  name: string;
  columns: string[];
  sample_rows: ExcelRow[];
}

/**
 * Reads every sheet in an uploaded workbook and returns its shape (sheet
 * names, columns, and a couple of sample rows) so the mapping UI can show
 * real values as a guide while the user maps fields.
 */
export async function inspectWorkbook(source: string | Buffer): Promise<{ sheets: InspectedSheet[] }> {
  const workbook = await readWorkbook(source);
  const sheets: InspectedSheet[] = workbook.worksheets.map((worksheet) => {
    const columns = getHeaders(worksheet).filter(Boolean);
    // Only the first 3 rows are ever shown -- bounding sheetToRecords to that
    // avoids materializing an entire real ~70k-row sheet just to immediately
    // discard all but the first 3 (see sheetToRecords' maxRows doc comment).
    const sampleRows = sheetToRecords(worksheet, undefined, 3);
    return { name: worksheet.name, columns, sample_rows: sampleRows };
  });
  return { sheets };
}

interface LoadedSheet {
  headers: string[];
  headerSet: Set<string>;
  records: ExcelRow[];
}

function loadSheet(workbook: Awaited<ReturnType<typeof readWorkbook>>, sheetName: string): LoadedSheet {
  const worksheet = workbook.getWorksheet(sheetName);
  if (!worksheet) {
    throw new Error(`Sheet '${sheetName}' not found in the uploaded file.`);
  }
  const headers = getHeaders(worksheet);
  return {
    headers,
    headerSet: new Set(headers.filter(Boolean)),
    records: sheetToRecords(worksheet, headers),
  };
}

/**
 * Validates a mapped column exists, raising a clear error rather than
 * silently treating the field as unmapped -- a wrong mapping should fail
 * loudly, not quietly produce all-null data.
 */
function assertColumnExists(sheet: LoadedSheet, sheetName: string, column: string): void {
  if (!sheet.headerSet.has(column)) {
    throw new Error(`Column '${column}' not found on sheet '${sheetName}'. Check the mapping.`);
  }
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** ANDs together a list of {column, match_type, values} conditions. */
function applyFilters(sheet: LoadedSheet, sheetName: string, filters: FilterConfig[]): ExcelRow[] {
  let records = sheet.records;
  for (const filter of filters) {
    const { column, match_type: matchType, values } = filter;
    assertColumnExists(sheet, sheetName, column);
    if (matchType === 'equals') {
      const target = String(values[0]).trim();
      records = records.filter((r) => {
        const raw = r[column];
        const asString = raw === null || raw === undefined ? '' : String(raw);
        return asString.trim() === target;
      });
    } else if (matchType === 'contains_any') {
      const pattern = new RegExp(values.map(escapeRegExp).join('|'));
      records = records.filter((r) => {
        const raw = r[column];
        const asString = raw === null || raw === undefined ? '' : String(raw);
        return pattern.test(asString);
      });
    } else {
      throw new Error(`Unknown match_type: ${matchType}`);
    }
  }
  return records;
}

/** First value of `column` per normalized group-by key, in row order -- for
 * fields that live on the line-items sheet rather than the primary one.
 * Matches pandas groupby's default of dropping rows whose key is null. */
function resolvePerCustomerColumn(sheet: LoadedSheet, sheetName: string, groupByColumn: string, column: string): Map<string, unknown> {
  assertColumnExists(sheet, sheetName, column);
  assertColumnExists(sheet, sheetName, groupByColumn);
  const result = new Map<string, unknown>();
  for (const record of sheet.records) {
    const key = normalizeIdValue(record[groupByColumn]);
    if (key === null) continue;
    if (!result.has(key)) result.set(key, record[column]);
  }
  return result;
}

function coerceNumeric(value: unknown): number {
  if (value === null || value === undefined) return 0;
  if (typeof value === 'number') return Number.isNaN(value) ? 0 : value;
  const parsed = Number(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function sumByGroup(records: ExcelRow[], groupByColumn: string, valueColumn: string): Map<string, number> {
  const sums = new Map<string, number>();
  for (const record of records) {
    const key = normalizeIdValue(record[groupByColumn]);
    if (key === null) continue;
    const value = coerceNumeric(record[valueColumn]);
    sums.set(key, (sums.get(key) ?? 0) + value);
  }
  return sums;
}

function deriveBillingMonth(raw: unknown): string | null {
  if (raw === null || raw === undefined) return null;
  const date = raw instanceof Date ? raw : new Date(String(raw));
  if (Number.isNaN(date.getTime())) return null;
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, '0');
  return `${year}-${month}`;
}

/**
 * Generic replacement for a client-specific loader: builds a STANDARD_SCHEMA
 * row set entirely from a user-configured mapping instead of hardcoded
 * column names. See backend/mappings/electra_default.json for an example.
 *
 * A field_mappings/billing_month entry may live on the "primary" sheet
 * (whichever sheet meter_number is mapped from, one row per meter) or on the
 * shared line-items sheet (one row per billing line, aggregated per
 * customer) -- no other sheet is supported for those, since there'd be no
 * defined join key to reach it. Calculated fields are different: each one
 * carries its own sheet + group_by_column, fully independent of the shared
 * line-items sheet and of every other calculated field.
 */
export async function loadMappedData(source: string | Buffer, mapping: MappingConfig): Promise<StandardRow[]> {
  const workbook = await readWorkbook(source);
  logger.info('CLIENT LOAD: mapping in use:', JSON.stringify(mapping, null, 2));

  const fieldMappings = mapping.field_mappings ?? {};
  const billingMonthCfg = mapping.billing_month;
  const lineItemsCfg = mapping.line_items;
  const calculatedFields = mapping.calculated_fields ?? {};

  if (!fieldMappings.meter_number || !fieldMappings.customer_id) {
    throw new Error('meter_number and customer_id must be mapped');
  }

  const primarySheetName = fieldMappings.meter_number.sheet;
  const primarySheet = loadSheet(workbook, primarySheetName);

  const lineItemsSheetName = lineItemsCfg?.sheet ?? null;
  const lineItemsSheet = lineItemsSheetName ? loadSheet(workbook, lineItemsSheetName) : null;
  const groupByColumn = lineItemsCfg?.group_by_column ?? null;
  if (lineItemsSheet && groupByColumn) {
    assertColumnExists(lineItemsSheet, lineItemsSheetName!, groupByColumn);
  }

  // customer_id must live on the primary sheet -- it's the anchor used to
  // join in any fields that live on the line-items sheet instead.
  const customerIdCfg = fieldMappings.customer_id;
  if (customerIdCfg.sheet !== primarySheetName) {
    throw new Error('customer_id must be mapped from the same sheet as meter_number');
  }
  assertColumnExists(primarySheet, primarySheetName, customerIdCfg.column);

  logger.info(
    `CLIENT LOAD: read sheet(s): primary='${primarySheetName}' (${primarySheet.records.length} rows)` +
      (lineItemsSheetName ? `, line_items='${lineItemsSheetName}' (${lineItemsSheet!.records.length} rows)` : '')
  );

  // One working row per primary-sheet record, carrying its own normalized
  // customer_id alongside the eventual STANDARD_SCHEMA fields.
  const rows = primarySheet.records.map((primaryRecord) => {
    const row = Object.fromEntries(STANDARD_SCHEMA.map((field) => [field, null])) as StandardRow;
    row.customer_id = normalizeIdValue(primaryRecord[customerIdCfg.column]);
    return { primaryRecord, row };
  });

  for (const [targetKey, cfg] of Object.entries(fieldMappings)) {
    if (targetKey === 'customer_id') continue;
    const { sheet: sheetName, column } = cfg;
    if (sheetName === primarySheetName) {
      assertColumnExists(primarySheet, sheetName, column);
      for (const { primaryRecord, row } of rows) {
        (row as Record<string, unknown>)[targetKey] = primaryRecord[column];
      }
    } else if (lineItemsSheet && sheetName === lineItemsSheetName) {
      const perCustomer = resolvePerCustomerColumn(lineItemsSheet, sheetName, groupByColumn!, column);
      for (const { row } of rows) {
        (row as Record<string, unknown>)[targetKey] = row.customer_id ? perCustomer.get(row.customer_id as string) ?? null : null;
      }
    } else {
      throw new Error(
        `Field '${targetKey}' references sheet '${sheetName}', which is neither ` +
          'the primary sheet (from meter_number\'s mapping) nor the line-items sheet.'
      );
    }
  }

  // --- Billing month: either a direct column, or derived from a date column ---
  if (billingMonthCfg) {
    const mode = billingMonthCfg.mode ?? 'direct';
    const { sheet: sheetName, column } = billingMonthCfg;
    let rawByRow: Map<{ primaryRecord: ExcelRow; row: StandardRow }, unknown>;
    if (sheetName === primarySheetName) {
      assertColumnExists(primarySheet, sheetName, column);
      rawByRow = new Map(rows.map((r) => [r, r.primaryRecord[column]]));
    } else if (lineItemsSheet && sheetName === lineItemsSheetName) {
      const perCustomer = resolvePerCustomerColumn(lineItemsSheet, sheetName, groupByColumn!, column);
      rawByRow = new Map(rows.map((r) => [r, r.row.customer_id ? perCustomer.get(r.row.customer_id as string) ?? null : null]));
    } else {
      throw new Error(`billing_month references unknown sheet '${sheetName}'`);
    }

    for (const entry of rows) {
      const raw = rawByRow.get(entry);
      entry.row.billing_month = mode === 'derive_from_date' ? deriveBillingMonth(raw) : raw ?? null;
    }
  }

  // --- Calculated fields: each one is fully independent -- its own sheet,
  // its own group-by column, its own value column and filters. Picking a
  // sheet for one calculated field has no effect on any other field, and
  // none of them share the field_mappings/billing_month line-items sheet
  // above (a calculated field may live on a completely different sheet).
  for (const [targetKey, rule] of Object.entries(calculatedFields)) {
    const calcSheet = loadSheet(workbook, rule.sheet);
    assertColumnExists(calcSheet, rule.sheet, rule.value_column);
    assertColumnExists(calcSheet, rule.sheet, rule.group_by_column);
    const filtered = applyFilters(calcSheet, rule.sheet, rule.filters ?? []);
    const summed = sumByGroup(filtered, rule.group_by_column, rule.value_column);

    let missing = 0;
    for (const { row } of rows) {
      const key = row.customer_id as string | null;
      const value = key !== null && summed.has(key) ? summed.get(key)! : null;
      (row as Record<string, unknown>)[targetKey] = value;
      if (value === null) missing += 1;
    }
    logger.info(
      `CLIENT LOAD: calculated '${targetKey}' from sheet '${rule.sheet}' (${filtered.length}/${calcSheet.records.length} ` +
        `rows matched filters, ${summed.size} distinct customers summed, ${missing} customers with no matching rows -> null)`
    );
  }

  // meter_number isn't run through normalizeIdValue above (only customer_id
  // is, as the join key), so this is its only cleanup pass.
  const final = rows.map(({ row }) => {
    row.meter_number = normalizeIdValue(row.meter_number);
    row.customer_id = normalizeIdValue(row.customer_id);
    return row;
  });

  logger.info(`CLIENT LOAD: final rows: ${final.length}`);
  logger.debug('CLIENT LOAD: final rows:', JSON.stringify(final));
  return final;
}
