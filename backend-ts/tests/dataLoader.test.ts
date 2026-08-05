import { describe, it, expect, afterEach } from 'vitest';
import ExcelJS from 'exceljs';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { loadAltecoData, normalizeIdValue } from '../src/dataLoader.js';

async function writeAltecoFixture(rows: Array<Record<string, unknown>>): Promise<string> {
  const workbook = new ExcelJS.Workbook();
  const worksheet = workbook.addWorksheet('חשבונית חוזה');
  const headers = rows.length > 0 ? Object.keys(rows[0]) : [];
  worksheet.addRow(headers);
  for (const row of rows) {
    worksheet.addRow(headers.map((h) => row[h] ?? null));
  }
  const filePath = path.join(os.tmpdir(), `alteco-fixture-${Date.now()}-${Math.random().toString(36).slice(2)}.xlsx`);
  await workbook.xlsx.writeFile(filePath);
  return filePath;
}

describe('loadAltecoData', () => {
  const tempFiles: string[] = [];
  afterEach(() => {
    for (const f of tempFiles.splice(0)) {
      if (fs.existsSync(f)) fs.unlinkSync(f);
    }
  });

  it('strips whitespace and renames columns to the standard schema', async () => {
    const filePath = await writeAltecoFixture([
      { 'מספר מונה': ' M-11111 ', 'חודש חיוב': '2026-05', 'סה״כ צריכה קוט״ש': 1000 },
    ]);
    tempFiles.push(filePath);

    const rows = await loadAltecoData(filePath);
    expect(rows[0].meter_number).toBe('M-11111');
    expect(rows[0].total_kwh).toBe(1000);
    expect(rows[0].billing_month).toBe('2026-05');
  });

  it('normalizes a genuinely blank customer_id to null, not a stray artifact', async () => {
    const filePath = await writeAltecoFixture([
      { 'מספר מונה': 'M-1', 'מספר לקוח': 377007686 },
      { 'מספר מונה': 'M-2', 'מספר לקוח': null },
    ]);
    tempFiles.push(filePath);

    const rows = await loadAltecoData(filePath);
    expect(rows[0].customer_id).toBe('377007686');
    expect(rows[0].customer_id).not.toContain('.0');
    expect(rows[1].customer_id).toBeNull();
  });

  it('leaves a field entirely null (not a crash) when its Alteco column is missing', async () => {
    const filePath = await writeAltecoFixture([{ 'מספר מונה': 'M-1' }]);
    tempFiles.push(filePath);

    const rows = await loadAltecoData(filePath);
    expect(rows[0].total_kwh).toBeNull();
    expect(rows[0].meter_number).toBe('M-1');
  });

  it('throws a clear error when the expected sheet is missing', async () => {
    const workbook = new ExcelJS.Workbook();
    workbook.addWorksheet('some other sheet');
    const filePath = path.join(os.tmpdir(), `bad-fixture-${Date.now()}.xlsx`);
    await workbook.xlsx.writeFile(filePath);
    tempFiles.push(filePath);

    await expect(loadAltecoData(filePath)).rejects.toThrow(/חשבונית חוזה/);
  });
});

describe('normalizeIdValue', () => {
  it('handles whole numbers, strings, whitespace, and blanks', () => {
    expect(normalizeIdValue(377007686)).toBe('377007686');
    expect(normalizeIdValue('377007686')).toBe('377007686');
    expect(normalizeIdValue('  M-1  ')).toBe('M-1');
    expect(normalizeIdValue(null)).toBeNull();
    expect(normalizeIdValue(undefined)).toBeNull();
  });
});
