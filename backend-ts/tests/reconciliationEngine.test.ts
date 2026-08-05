import { describe, it, expect } from 'vitest';
import { ReconciliationEngine } from '../src/reconciliationEngine.js';
import { STANDARD_SCHEMA, StandardRow } from '../src/dataLoader.js';

function makeRow(overrides: Partial<StandardRow> = {}): StandardRow {
  const row = Object.fromEntries(STANDARD_SCHEMA.map((f) => [f, null])) as StandardRow;
  return { ...row, ...overrides };
}

describe('ReconciliationEngine', () => {
  it('a perfect match generates zero discrepancies', () => {
    const alteco = [
      makeRow({
        meter_number: 'M-GOOD',
        billing_month: '2026-05',
        customer_id: '12345',
        customer_name: 'Perfect Client Ltd',
        tax_id: '515151',
        iec_contract: '999888',
        contract_start_date: '2024-01-01',
        total_kwh: 1000.0,
      }),
    ];
    const client = alteco.map((r) => ({ ...r }));
    const results = new ReconciliationEngine(alteco, client).runAllSteps();
    expect(results.step0).toHaveLength(0);
    expect(results.step1).toHaveLength(0);
    expect(results.step2).toHaveLength(0);
    expect(results.step3).toHaveLength(0);
  });

  it('catches multiple field mismatches in phase 1', () => {
    const alteco = [makeRow({ meter_number: 'M-ERR-1', billing_month: '2026-05', customer_name: 'Company A' })];
    const client = [makeRow({ meter_number: 'M-ERR-1', billing_month: '2026-05', customer_name: 'Company B' })];
    // billing_days isn't in STANDARD_SCHEMA, so mirror the Python test's intent
    // (a numeric field mismatch) using a field that actually exists: kva.
    (alteco[0] as Record<string, unknown>).kva = 31;
    (client[0] as Record<string, unknown>).kva = 28;

    const results = new ReconciliationEngine(alteco, client).runAllSteps();
    const fields = results.step1.map((r) => r['Mismatched Field']);
    expect(fields).toContain('KVA');
    expect(fields).toContain('Customer Name');
  });

  it('is type-resilient to mixed numeric/string formats for the same value', () => {
    const alteco = [makeRow({ meter_number: 'M-TYPE', kva: '31' as unknown as number })];
    const client = [makeRow({ meter_number: 'M-TYPE', kva: 31 })];
    const results = new ReconciliationEngine(alteco, client).runAllSteps();
    expect(results.step1).toHaveLength(0);
  });

  it('flags a field present on only one side as a reportable gap, not a silent skip', () => {
    const alteco = [makeRow({ meter_number: 'M-MISSING', tax_id: null })];
    const client = [makeRow({ meter_number: 'M-MISSING', tax_id: '515151' })];
    const results = new ReconciliationEngine(alteco, client).runAllSteps();
    expect(results.step1).toHaveLength(1);
    expect(results.step1[0]['Mismatched Field']).toBe('Tax ID');
    expect(results.step1[0]['Alteco Value']).toBeNull();
    expect(results.step1[0]['Client Value']).toBe('515151');
  });

  it('skips a field missing on both sides without crashing', () => {
    const alteco = [makeRow({ meter_number: 'M-BOTH-MISSING', tax_id: null })];
    const client = [makeRow({ meter_number: 'M-BOTH-MISSING', tax_id: null })];
    const results = new ReconciliationEngine(alteco, client).runAllSteps();
    expect(results.step1).toHaveLength(0);
  });

  it('step 2: a small diff within tolerance (<= 0.5) is ignored', () => {
    const alteco = [makeRow({ meter_number: 'M-TOLERANCE', total_kwh: 1000.0 })];
    const client = [makeRow({ meter_number: 'M-TOLERANCE', total_kwh: 1000.4 })];
    const results = new ReconciliationEngine(alteco, client).runAllSteps();
    expect(results.step2).toHaveLength(0);
  });

  it('step 2: a diff exceeding tolerance (> 0.5) is flagged', () => {
    const alteco = [makeRow({ meter_number: 'M-DIFF', total_kwh: 1000.0 })];
    const client = [makeRow({ meter_number: 'M-DIFF', total_kwh: 1001.0 })];
    const results = new ReconciliationEngine(alteco, client).runAllSteps();
    expect(results.step2).toHaveLength(1);
    expect(results.step2.map((r) => r['Mismatched Field'])).toContain('Total Consumption (kWh)');
  });

  it('step 2: consumption present on only one side is flagged, not silently skipped', () => {
    const alteco = [makeRow({ meter_number: 'M-BLANK-KWH', total_kwh: null })];
    const client = [makeRow({ meter_number: 'M-BLANK-KWH', total_kwh: 250.0 })];
    const results = new ReconciliationEngine(alteco, client).runAllSteps();
    expect(results.step2).toHaveLength(1);
    expect(results.step2[0]['Mismatched Field']).toBe('Total Consumption (kWh)');
    expect(results.step2[0]['Alteco Value']).toBeNull();
    expect(results.step2[0]['Client Value']).toBe(250.0);
  });

  it('step 0: flags a meter Alteco bills that Electra has no record of', () => {
    const alteco = [makeRow({ meter_number: 'M-ORPHAN', customer_name: 'Ghost Client' })];
    const client = [makeRow({ meter_number: 'M-OTHER', customer_name: 'Other Client' })];
    const results = new ReconciliationEngine(alteco, client).runAllSteps();
    expect(results.step0).toHaveLength(2);

    const orphan = results.step0.find((r) => r.Value === 'M-ORPHAN')!;
    expect(orphan['Match Key']).toBe('Meter Number');
    expect(orphan.Issue).toBe('Missing from Electra');

    const other = results.step0.find((r) => r.Value === 'M-OTHER')!;
    expect(other['Match Key']).toBe('Meter Number');
    expect(other.Issue).toBe('Missing from Alteco');

    expect(results.step1).toHaveLength(0);
    expect(results.step2).toHaveLength(0);
  });

  it('step 0: empty when all meters match', () => {
    const alteco = [makeRow({ meter_number: 'M-MATCH', customer_name: 'Same Client' })];
    const client = [makeRow({ meter_number: 'M-MATCH', customer_name: 'Same Client' })];
    const results = new ReconciliationEngine(alteco, client).runAllSteps();
    expect(results.step0).toHaveLength(0);
  });

  it('step 0: flags a customer missing even when meter numbers differ', () => {
    const alteco = [
      makeRow({ meter_number: 'M-A1', customer_id: 'C-1', customer_name: 'Client One' }),
      makeRow({ meter_number: 'M-A2', customer_id: 'C-GHOST', customer_name: 'Ghost Customer' }),
    ];
    const client = [makeRow({ meter_number: 'M-A1', customer_id: 'C-1', customer_name: 'Client One' })];
    const results = new ReconciliationEngine(alteco, client).runAllSteps();
    const customerGaps = results.step0.filter((r) => r['Match Key'] === 'Customer ID');
    expect(customerGaps).toHaveLength(1);
    expect(customerGaps[0].Value).toBe('C-GHOST');
    expect(customerGaps[0].Issue).toBe('Missing from Electra');
  });

  it('step 3: flags KVA and total payment mismatches', () => {
    const alteco = [
      makeRow({
        meter_number: 'M-FIN',
        customer_id: 'C-FIN',
        customer_name: 'Finance Client',
        total_payment: 100.0,
        kva_fixed_charge: 20.0,
        supply_fixed_charge: 5.0,
        distribution_fixed_charge: 5.0,
      }),
    ];
    const client = [
      makeRow({
        meter_number: 'M-FIN',
        customer_id: 'C-FIN',
        customer_name: 'Finance Client',
        total_payment: 130.0,
        kva_fixed_charge: 25.0,
        supply_fixed_charge: 5.0,
        distribution_fixed_charge: 5.0,
      }),
    ];
    const results = new ReconciliationEngine(alteco, client).runAllSteps();
    expect(results.step3).toHaveLength(2);
    const fields = new Set(results.step3.map((r) => r['Mismatched Field']));
    expect(fields).toEqual(new Set(['Total Payment (Incl. VAT)', 'KVA Fixed Charge']));
  });

  it('step 3: sums multiple Alteco meters per customer before comparing', () => {
    const alteco = [
      makeRow({ meter_number: 'M-MULTI-1', customer_id: 'C-MULTI', customer_name: 'Multi Meter Client', total_payment: 60.0 }),
      makeRow({ meter_number: 'M-MULTI-2', customer_id: 'C-MULTI', customer_name: 'Multi Meter Client', total_payment: 40.0 }),
    ];
    const client = [makeRow({ meter_number: 'M-MULTI-1', customer_id: 'C-MULTI', customer_name: 'Multi Meter Client', total_payment: 100.0 })];
    const results = new ReconciliationEngine(alteco, client).runAllSteps();
    expect(results.step3).toHaveLength(0);
  });

  it('step 3: empty when no financial data is present', () => {
    const alteco = [makeRow({ meter_number: 'M-NOFIN', customer_id: 'C-NOFIN' })];
    const client = [makeRow({ meter_number: 'M-NOFIN', customer_id: 'C-NOFIN' })];
    const results = new ReconciliationEngine(alteco, client).runAllSteps();
    expect(results.step3).toHaveLength(0);
  });

  // ---- Edge cases ----

  it('KNOWN LIMITATION: a duplicate meter number on both sides cross-pairs (2x2, not 1:1)', () => {
    const alteco = [
      makeRow({ meter_number: 'M-DUP', customer_id: 'C-A', customer_name: 'Alpha' }),
      makeRow({ meter_number: 'M-DUP', customer_id: 'C-B', customer_name: 'Beta' }),
    ];
    const client = [
      makeRow({ meter_number: 'M-DUP', customer_id: 'C-A', customer_name: 'Alpha' }),
      makeRow({ meter_number: 'M-DUP', customer_id: 'C-B', customer_name: 'Beta' }),
    ];
    const engine = new ReconciliationEngine(alteco, client);
    expect(engine.matched).toHaveLength(4); // 2x2 cross product, not 2

    const results = engine.runAllSteps();
    const customerIdMismatches = results.step1.filter((r) => r['Mismatched Field'] === 'Customer ID');
    expect(customerIdMismatches).toHaveLength(2); // the (A,B) and (B,A) cross-pairs

    // The duplicate itself is logged, but deliberately kept out of Meter
    // Coverage -- it's a data-quality issue, not a "missing from one side" gap.
    expect(results.step0).toHaveLength(0);
  });

  it('a meter duplicated on only one side does not add a coverage row for the duplicate itself', () => {
    const alteco = [
      makeRow({ meter_number: 'M-SOLO-DUP', customer_id: 'C-X', customer_name: 'X Corp' }),
      makeRow({ meter_number: 'M-SOLO-DUP', customer_id: 'C-Y', customer_name: 'Y Corp' }),
    ];
    const client = [makeRow({ meter_number: 'M-SOLO-DUP', customer_id: 'C-X', customer_name: 'X Corp' })];
    const results = new ReconciliationEngine(alteco, client).runAllSteps();

    expect(results.step0.some((r) => r.Issue.includes('Duplicate meter number'))).toBe(false);
    expect(results.step0).toHaveLength(1);
    expect(results.step0[0]['Match Key']).toBe('Customer ID');
    expect(results.step0[0].Value).toBe('C-Y');
  });

  it('no duplicate meter flagged when all unique', () => {
    const alteco = [makeRow({ meter_number: 'M-UNIQUE-1', customer_id: 'C-1' })];
    const client = [makeRow({ meter_number: 'M-UNIQUE-1', customer_id: 'C-1' })];
    const results = new ReconciliationEngine(alteco, client).runAllSteps();
    expect(results.step0).toHaveLength(0);
  });

  it('only the Alteco-side billing_month is reformatted -- a raw client value is not, and shows as a false mismatch', () => {
    const alteco = [makeRow({ meter_number: 'M-BM', billing_month: '2026-06' })];
    const client = [makeRow({ meter_number: 'M-BM', billing_month: new Date('2026-06-30T00:00:00.000Z') })];
    const results = new ReconciliationEngine(alteco, client).runAllSteps();
    expect(results.step1).toHaveLength(1);
    expect(results.step1[0]['Mismatched Field']).toBe('Billing Month');
  });

  it('empty inputs do not crash', () => {
    const results = new ReconciliationEngine([], []).runAllSteps();
    expect(results.step0).toHaveLength(0);
    expect(results.step1).toHaveLength(0);
    expect(results.step2).toHaveLength(0);
    expect(results.step3).toHaveLength(0);
  });
});
