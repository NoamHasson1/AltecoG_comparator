import { describe, it, expect } from 'vitest';
import ExcelJS from 'exceljs';
import { buildDiscrepancyWorkbook } from '../src/exportReport.js';

async function readBack(buffer: Buffer): Promise<ExcelJS.Workbook> {
  const workbook = new ExcelJS.Workbook();
  await workbook.xlsx.load(buffer as any); // eslint-disable-line @typescript-eslint/no-explicit-any -- same exceljs Buffer-type bug noted in excelUtils.ts
  return workbook;
}

describe('buildDiscrepancyWorkbook', () => {
  it('builds a Summary sheet plus one sheet per phase, with correct mismatch counts', async () => {
    const results = {
      step0: [{ 'Match Key': 'Meter Number', Value: 'M-1', 'Client Name': 'Ghost Client', Issue: 'Missing from Electra' }],
      step1: [],
      step2: [
        {
          'Meter Number': 'M-2',
          'Client Name': 'Real Client',
          'Mismatched Field': 'Total Consumption (kWh)',
          'Original Field (Hebrew)': 'סה״כ צריכה קוט״ש',
          'Alteco Value': 100,
          'Client Value': 105,
        },
      ],
      step3: [],
    };

    const buffer = await buildDiscrepancyWorkbook(results);
    const workbook = await readBack(buffer);

    const sheetNames = workbook.worksheets.map((w) => w.name);
    expect(sheetNames).toEqual(['Summary', 'Meter Coverage', 'Metadata', 'Consumption', 'Financial']);

    const summary = workbook.getWorksheet('Summary')!;
    expect(summary.getRow(1).getCell(1).value).toBe('Phase');
    expect(summary.getRow(2).getCell(1).value).toBe('Meter Coverage');
    expect(summary.getRow(2).getCell(2).value).toBe(1);
    expect(summary.getRow(4).getCell(1).value).toBe('Consumption');
    expect(summary.getRow(4).getCell(2).value).toBe(1);
    expect(summary.getCell('C1').value).toBe('Generated');
    expect(typeof summary.getCell('C2').value).toBe('string');
  });

  it('gives an empty phase a "no discrepancies found" placeholder row instead of an empty sheet', async () => {
    const results = { step0: [], step1: [], step2: [], step3: [] };
    const buffer = await buildDiscrepancyWorkbook(results);
    const workbook = await readBack(buffer);

    const metadata = workbook.getWorksheet('Metadata')!;
    expect(metadata.getRow(1).getCell(1).value).toBe('Result');
    expect(metadata.getRow(2).getCell(1).value).toBe('No discrepancies found');
  });

  it('applies bold white-on-dark header styling and freezes the header row', async () => {
    const results = { step0: [{ 'Match Key': 'x', Value: 'y', 'Client Name': 'z', Issue: 'w' }], step1: [], step2: [], step3: [] };
    const buffer = await buildDiscrepancyWorkbook(results);
    const workbook = await readBack(buffer);

    const sheet = workbook.getWorksheet('Meter Coverage')!;
    const headerCell = sheet.getRow(1).getCell(1);
    expect(headerCell.font?.bold).toBe(true);
    expect(sheet.views?.[0]).toMatchObject({ state: 'frozen', ySplit: 1 });
  });

  it('only includes actual data columns from the defined column list, in order', async () => {
    const results = {
      step0: [{ 'Match Key': 'Meter Number', Value: 'M-1', 'Client Name': 'X', Issue: 'Missing from Electra' }],
      step1: [],
      step2: [],
      step3: [],
    };
    const buffer = await buildDiscrepancyWorkbook(results);
    const workbook = await readBack(buffer);
    const sheet = workbook.getWorksheet('Meter Coverage')!;
    const headerValues = [1, 2, 3, 4].map((c) => sheet.getRow(1).getCell(c).value);
    expect(headerValues).toEqual(['Match Key', 'Value', 'Client Name', 'Issue']);
  });
});
