import { describe, it, expect, afterEach } from 'vitest';
import ExcelJS from 'exceljs';
import os from 'node:os';
import path from 'node:path';
import { inspectWorkbook, loadMappedData, MappingConfig } from '../src/dynamicLoader.js';
import { writeWorkbook, trackTempFiles } from './testFixtures.js';

const temp = trackTempFiles();
afterEach(() => temp.cleanup());

async function baseFixture() {
  return writeWorkbook([
    {
      name: 'Meta',
      rows: [
        { CustomerID: 'C1', MeterNo: 'M-1', Status: 'Active' },
        { CustomerID: 'C2', MeterNo: 'M-2', Status: 'Active' },
        { CustomerID: 'C3', MeterNo: 'M-3', Status: 'Inactive' },
      ],
    },
    {
      name: 'Lines',
      rows: [
        { AcctID: 'C1', LineType: 'Usage', Description: 'Night rate', Qty: 10, Amount: 100.0 },
        { AcctID: 'C1', LineType: 'Usage', Description: 'Day rate', Qty: 20, Amount: 200.0 },
        { AcctID: 'C1', LineType: 'Fixed', Description: 'KVA charge', Qty: 5, Amount: 50.0 },
        { AcctID: 'C2', LineType: 'Usage', Description: 'Day rate', Qty: 40, Amount: 400.0 },
      ],
    },
  ]);
}

function baseMapping(): MappingConfig {
  return {
    field_mappings: {
      customer_id: { sheet: 'Meta', column: 'CustomerID' },
      meter_number: { sheet: 'Meta', column: 'MeterNo' },
    },
    line_items: { sheet: 'Lines', group_by_column: 'AcctID' },
    calculated_fields: {},
  };
}

describe('inspectWorkbook', () => {
  it('returns sheets, columns, and sample rows', async () => {
    const filePath = temp.track(await baseFixture());
    const result = await inspectWorkbook(filePath);
    const sheetNames = result.sheets.map((s) => s.name);
    expect(sheetNames).toContain('Meta');
    expect(sheetNames).toContain('Lines');

    const metaSheet = result.sheets.find((s) => s.name === 'Meta')!;
    expect(metaSheet.columns).toEqual(['CustomerID', 'MeterNo', 'Status']);
    expect(metaSheet.sample_rows).toHaveLength(3);
    expect(metaSheet.sample_rows[0].CustomerID).toBe('C1');
  });
});

describe('loadMappedData', () => {
  it('includes all meters regardless of status (no active/inactive filtering)', async () => {
    const filePath = temp.track(await baseFixture());
    const rows = await loadMappedData(filePath, baseMapping());
    expect(rows).toHaveLength(3);
    expect(rows.map((r) => r.meter_number)).toContain('M-3');
  });

  it('equals filter matches exact type', async () => {
    const filePath = temp.track(await baseFixture());
    const mapping = baseMapping();
    mapping.calculated_fields!.total_kwh = {
      sheet: 'Lines',
      group_by_column: 'AcctID',
      value_column: 'Qty',
      filters: [{ column: 'LineType', match_type: 'equals', values: ['Usage'] }],
    };
    const rows = await loadMappedData(filePath, mapping);
    const c1 = rows.find((r) => r.customer_id === 'C1')!;
    expect(c1.total_kwh).toBe(30);
  });

  it('contains_any filter matches keywords', async () => {
    const filePath = temp.track(await baseFixture());
    const mapping = baseMapping();
    mapping.calculated_fields!.kva_fixed_charge = {
      sheet: 'Lines',
      group_by_column: 'AcctID',
      value_column: 'Amount',
      filters: [{ column: 'Description', match_type: 'contains_any', values: ['KVA'] }],
    };
    const rows = await loadMappedData(filePath, mapping);
    const c1 = rows.find((r) => r.customer_id === 'C1')!;
    expect(c1.kva_fixed_charge).toBe(50);
  });

  it('combined filters are ANDed together', async () => {
    const filePath = temp.track(await baseFixture());
    const mapping = baseMapping();
    mapping.calculated_fields!.total_kwh = {
      sheet: 'Lines',
      group_by_column: 'AcctID',
      value_column: 'Qty',
      filters: [
        { column: 'LineType', match_type: 'equals', values: ['Usage'] },
        { column: 'Description', match_type: 'contains_any', values: ['Night'] },
      ],
    };
    const rows = await loadMappedData(filePath, mapping);
    const c1 = rows.find((r) => r.customer_id === 'C1')!;
    expect(c1.total_kwh).toBe(10);
  });

  it('no filters sums everything', async () => {
    const filePath = temp.track(await baseFixture());
    const mapping = baseMapping();
    mapping.calculated_fields!.total_payment = {
      sheet: 'Lines',
      group_by_column: 'AcctID',
      value_column: 'Amount',
      filters: [],
    };
    const rows = await loadMappedData(filePath, mapping);
    const c1 = rows.find((r) => r.customer_id === 'C1')!;
    expect(c1.total_payment).toBe(350);
  });

  it('throws when a field references an unknown sheet', async () => {
    const filePath = temp.track(await baseFixture());
    const mapping = baseMapping();
    mapping.field_mappings.customer_name = { sheet: 'NoSuchSheet', column: 'X' };
    await expect(loadMappedData(filePath, mapping)).rejects.toThrow();
  });

  it('throws when meter_number is not mapped', async () => {
    const filePath = temp.track(await baseFixture());
    const mapping = baseMapping();
    delete (mapping.field_mappings as Record<string, unknown>).meter_number;
    await expect(loadMappedData(filePath, mapping)).rejects.toThrow();
  });

  it('leaves an unmapped optional field null', async () => {
    const filePath = temp.track(await baseFixture());
    const rows = await loadMappedData(filePath, baseMapping());
    expect(rows.every((r) => r.tariff === null)).toBe(true);
  });

  // ---- Edge cases ----

  it('equals filter is case-sensitive (documents current behavior)', async () => {
    const filePath = temp.track(await baseFixture());
    const mapping = baseMapping();
    mapping.calculated_fields!.total_kwh = {
      sheet: 'Lines',
      group_by_column: 'AcctID',
      value_column: 'Qty',
      filters: [{ column: 'LineType', match_type: 'equals', values: ['usage'] }],
    };
    const rows = await loadMappedData(filePath, mapping);
    const c1 = rows.find((r) => r.customer_id === 'C1')!;
    expect(c1.total_kwh).toBeNull();
  });

  it('filter matching nothing yields null, not zero', async () => {
    const filePath = temp.track(await baseFixture());
    const mapping = baseMapping();
    mapping.calculated_fields!.kva_fixed_charge = {
      sheet: 'Lines',
      group_by_column: 'AcctID',
      value_column: 'Amount',
      filters: [{ column: 'Description', match_type: 'contains_any', values: ['NoSuchKeyword'] }],
    };
    const rows = await loadMappedData(filePath, mapping);
    const c1 = rows.find((r) => r.customer_id === 'C1')!;
    expect(c1.kva_fixed_charge).toBeNull();
  });

  it('a field from the line-items sheet takes the first row per customer, not an aggregate', async () => {
    const filePath = temp.track(await baseFixture());
    const mapping = baseMapping();
    mapping.field_mappings.customer_name = { sheet: 'Lines', column: 'Description' };
    const rows = await loadMappedData(filePath, mapping);
    const c1 = rows.find((r) => r.customer_id === 'C1')!;
    expect(c1.customer_name).toBe('Night rate');
  });

  it('contains_any treats regex special characters as literal substrings', async () => {
    const filePath = temp.track(
      await writeWorkbook([
        { name: 'Meta', rows: [{ CustomerID: 'C1', MeterNo: 'M-1' }] },
        {
          name: 'Lines',
          rows: [
            { AcctID: 'C1', Description: 'Fee (KVA)', Amount: 42.0 },
            { AcctID: 'C1', Description: 'Other charge', Amount: 10.0 },
          ],
        },
      ])
    );
    const mapping: MappingConfig = {
      field_mappings: {
        customer_id: { sheet: 'Meta', column: 'CustomerID' },
        meter_number: { sheet: 'Meta', column: 'MeterNo' },
      },
      line_items: { sheet: 'Lines', group_by_column: 'AcctID' },
      calculated_fields: {
        total_payment: {
          sheet: 'Lines',
          group_by_column: 'AcctID',
          value_column: 'Amount',
          filters: [{ column: 'Description', match_type: 'contains_any', values: ['(KVA)'] }],
        },
      },
    };
    const rows = await loadMappedData(filePath, mapping);
    const c1 = rows.find((r) => r.customer_id === 'C1')!;
    expect(c1.total_payment).toBe(42);
  });

  it('coerces non-numeric junk in the value column to zero rather than crashing', async () => {
    const filePath = temp.track(
      await writeWorkbook([
        { name: 'Meta', rows: [{ CustomerID: 'C1', MeterNo: 'M-1' }] },
        {
          name: 'Lines',
          rows: [
            { AcctID: 'C1', Amount: '100.5' },
            { AcctID: 'C1', Amount: 'N/A' },
            { AcctID: 'C1', Amount: 50 },
          ],
        },
      ])
    );
    const mapping: MappingConfig = {
      field_mappings: {
        customer_id: { sheet: 'Meta', column: 'CustomerID' },
        meter_number: { sheet: 'Meta', column: 'MeterNo' },
      },
      line_items: { sheet: 'Lines', group_by_column: 'AcctID' },
      calculated_fields: {
        total_payment: { sheet: 'Lines', group_by_column: 'AcctID', value_column: 'Amount', filters: [] },
      },
    };
    const rows = await loadMappedData(filePath, mapping);
    const c1 = rows.find((r) => r.customer_id === 'C1')!;
    expect(c1.total_payment).toBe(150.5);
  });

  it('calculated fields are fully independent of each other and of the shared line-items sheet', async () => {
    const filePath = temp.track(
      await writeWorkbook([
        { name: 'Meta', rows: [{ CustomerID: 'C1', MeterNo: 'M-1' }] },
        { name: 'Usage', rows: [{ UsageAcct: 'C1', Kwh: 100.0 }, { UsageAcct: 'C1', Kwh: 50.0 }] },
        { name: 'Billing', rows: [{ BillingCustomerRef: 'C1', Charge: 999.0 }] },
      ])
    );
    const mapping: MappingConfig = {
      field_mappings: {
        customer_id: { sheet: 'Meta', column: 'CustomerID' },
        meter_number: { sheet: 'Meta', column: 'MeterNo' },
      },
      calculated_fields: {
        total_kwh: { sheet: 'Usage', group_by_column: 'UsageAcct', value_column: 'Kwh', filters: [] },
        total_payment: { sheet: 'Billing', group_by_column: 'BillingCustomerRef', value_column: 'Charge', filters: [] },
      },
    };
    const rows = await loadMappedData(filePath, mapping);
    const c1 = rows.find((r) => r.customer_id === 'C1')!;
    expect(c1.total_kwh).toBe(150);
    expect(c1.total_payment).toBe(999);
  });

  it('customer_id and meter_number come out as clean strings', async () => {
    const filePath = temp.track(
      await writeWorkbook([{ name: 'Meta', rows: [{ CustomerID: 377007686, MeterNo: 50322013305 }, { CustomerID: null, MeterNo: 50322013306 }] }])
    );
    const mapping: MappingConfig = {
      field_mappings: {
        customer_id: { sheet: 'Meta', column: 'CustomerID' },
        meter_number: { sheet: 'Meta', column: 'MeterNo' },
      },
      calculated_fields: {},
    };
    const rows = await loadMappedData(filePath, mapping);
    expect(rows[0].customer_id).toBe('377007686');
    expect(rows[0].meter_number).toBe('50322013305');
    expect(rows[1].meter_number).toBe('50322013306');
    expect(rows[1].customer_id).toBeNull();
  });

  it('ignores phantom blank rows from a sheet whose technical row count is inflated by formatting-only cells', async () => {
    // Reproduces a real bug found via manual testing: real-world Excel files
    // very commonly have formatting (column-wide styles, leftover
    // formatting from a copy/paste) applied far past the actual data, which
    // inflates exceljs's worksheet.rowCount well beyond the real row count
    // (pandas' read_excel trims these automatically). Without handling this,
    // every one of those phantom rows shows up as a false "missing" coverage
    // gap -- seen as ~1900 bogus rows on a real file during manual testing.
    const workbook = new ExcelJS.Workbook();
    const worksheet = workbook.addWorksheet('Meta');
    worksheet.addRow(['CustomerID', 'MeterNo']);
    worksheet.addRow(['C1', 'M-1']);
    worksheet.addRow(['C2', 'M-2']);
    worksheet.getCell('A2000').style = { font: { bold: false } };
    const filePath = path.join(os.tmpdir(), `inflated-rowcount-${Date.now()}.xlsx`);
    await workbook.xlsx.writeFile(filePath);
    temp.track(filePath);

    const mapping: MappingConfig = {
      field_mappings: {
        customer_id: { sheet: 'Meta', column: 'CustomerID' },
        meter_number: { sheet: 'Meta', column: 'MeterNo' },
      },
      calculated_fields: {},
    };
    const rows = await loadMappedData(filePath, mapping);
    expect(rows).toHaveLength(2);
    expect(rows.map((r) => r.meter_number)).toEqual(['M-1', 'M-2']);
  });
});
