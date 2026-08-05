import { StandardRow } from './dataLoader.js';
import { outerJoin, JoinedRow } from './joinUtils.js';
import { createLogger } from './logger.js';

const logger = createLogger('reconciliationEngine');

function normalizeForComparison(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'number' && Number.isNaN(value)) return '';
  return String(value).trim();
}

function coerceNumeric(value: unknown): number {
  if (value === null || value === undefined) return 0;
  if (typeof value === 'number') return Number.isNaN(value) ? 0 : value;
  const parsed = Number(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function parseNumeric(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  const parsed = Number(value);
  return Number.isNaN(parsed) ? null : parsed;
}

function parseDateOrThrow(value: unknown): Date {
  const date = value instanceof Date ? value : new Date(String(value));
  if (Number.isNaN(date.getTime())) throw new Error(`Cannot parse date: ${String(value)}`);
  return date;
}

function formatDate(value: unknown, pattern: 'yyyy-MM' | 'yyyy-MM-dd'): string {
  const date = parseDateOrThrow(value);
  const year = date.getUTCFullYear();
  const month = String(date.getUTCMonth() + 1).padStart(2, '0');
  if (pattern === 'yyyy-MM') return `${year}-${month}`;
  const day = String(date.getUTCDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function splitWords(value: string): string[] {
  return value
    .split(/\s+/)
    .filter(Boolean)
    .sort();
}

function arraysEqual(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((v, i) => v === b[i]);
}

export interface CoverageGap {
  'Match Key': string;
  Value: unknown;
  'Client Name': unknown;
  Issue: string;
}

export interface FieldMismatch {
  'Meter Number': unknown;
  'Client Name': unknown;
  'Mismatched Field': string;
  'Original Field (Hebrew)': string;
  'Alteco Value': unknown;
  'Client Value': unknown;
}

export interface FinancialMismatch {
  'Customer ID': unknown;
  'Client Name': unknown;
  'Mismatched Field': string;
  'Original Field (Hebrew)': string;
  'Alteco Value': number;
  'Client Value': number;
}

export interface ReconciliationResults {
  step0: CoverageGap[];
  step1: FieldMismatch[];
  step2: FieldMismatch[];
  step3: FinancialMismatch[];
}

// [field, [English label, Hebrew label]] -- billing_days/basic/consumer_type
// aren't part of STANDARD_SCHEMA (no loader ever populates them), so they'll
// always read as undefined on both sides and get skipped as "both blank" --
// kept here anyway to mirror the Python engine's field list exactly.
const STEP1_FIELDS: Array<[string, [string, string]]> = [
  ['billing_month', ['Billing Month', 'חודש חיוב']],
  ['billing_days', ['Billing Days', 'ימים לחיוב']],
  ['customer_id', ['Customer ID', 'מספר לקוח']],
  ['customer_name', ['Customer Name', 'שם לקוח']],
  ['tax_id', ['Tax ID', 'ח.פ לקוח']],
  ['iec_contract', ['IEC Contract Number', 'מספר חוזה חח״י']],
  ['voltage', ['Voltage', 'מתח']],
  ['basic', ['Basic', 'בסיסי']],
  ['tou', ['TOU', 'תעו״ז']],
  ['consumer_type', ['Consumer Type', 'סוג צרכן']],
  ['billing_type', ['Billing Type', 'סוג חיוב']],
  ['tariff', ['Tariff', 'תעריף']],
  ['fixed_payment', ['Fixed Payment', 'תשלום קבוע']],
  ['contract_start_date', ['Contract Start Date', 'תאריך התחלת החוזה']],
  ['kva', ['KVA', 'KVA']],
];

const STEP2_FIELDS: Array<[string, [string, string]]> = [['total_kwh', ['Total Consumption (kWh)', 'סה״כ צריכה קוט״ש']]];

const STEP3_FIELDS: Array<[string, [string, string]]> = [
  ['total_payment', ['Total Payment (Incl. VAT)', 'סה״כ לתשלום (כולל מע״מ) ₪']],
  ['kva_fixed_charge', ['KVA Fixed Charge', 'חיוב קבוע KVA ₪']],
  ['supply_fixed_charge', ['Supply Fixed Charge', 'חיוב קבוע אספקה ₪']],
  ['distribution_fixed_charge', ['Distribution Fixed Charge', 'חיוב קבוע חלוקה ₪']],
];

const NUMERIC_STRICT_FIELDS = new Set(['billing_days', 'fixed_payment', 'kva']);
const STEP2_TOLERANCE = 0.5;
const STEP3_TOLERANCE = 0.5;

function dedupeByCustomerId(rows: StandardRow[]): Array<{ customer_id: string; customer_name: unknown }> {
  const seen = new Map<string, unknown>();
  for (const row of rows) {
    const id = row.customer_id as string | null;
    if (id === null || id === undefined) continue;
    if (!seen.has(id)) seen.set(id, row.customer_name);
  }
  return Array.from(seen.entries()).map(([customer_id, customer_name]) => ({ customer_id, customer_name }));
}

interface CustomerAggregate {
  customer_id: string;
  customer_name: unknown;
  total_payment: number;
  kva_fixed_charge: number;
  supply_fixed_charge: number;
  distribution_fixed_charge: number;
}

function aggregateByCustomer(rows: StandardRow[]): CustomerAggregate[] {
  const groups = new Map<string, CustomerAggregate>();
  for (const row of rows) {
    const customerId = row.customer_id as string | null;
    if (customerId === null || customerId === undefined) continue;
    if (!groups.has(customerId)) {
      groups.set(customerId, {
        customer_id: customerId,
        customer_name: row.customer_name,
        total_payment: 0,
        kva_fixed_charge: 0,
        supply_fixed_charge: 0,
        distribution_fixed_charge: 0,
      });
    }
    const g = groups.get(customerId)!;
    g.total_payment += coerceNumeric(row.total_payment);
    g.kva_fixed_charge += coerceNumeric(row.kva_fixed_charge);
    g.supply_fixed_charge += coerceNumeric(row.supply_fixed_charge);
    g.distribution_fixed_charge += coerceNumeric(row.distribution_fixed_charge);
  }
  return Array.from(groups.values());
}

export class ReconciliationEngine {
  private dfAlteco: StandardRow[];
  private dfClient: StandardRow[];
  private merged: JoinedRow<StandardRow, StandardRow>[];
  matched: JoinedRow<StandardRow, StandardRow>[];

  private discrepanciesStep0: CoverageGap[] = [];
  private discrepanciesStep1: FieldMismatch[] = [];
  private discrepanciesStep2: FieldMismatch[] = [];
  private discrepanciesStep3: FinancialMismatch[] = [];

  constructor(dfAlteco: StandardRow[], dfClient: StandardRow[]) {
    this.dfAlteco = dfAlteco;
    this.dfClient = dfClient;

    logger.info(`RECONCILE INIT: Alteco has ${dfAlteco.length} rows`);
    logger.debug('RECONCILE INIT: Alteco rows:', JSON.stringify(dfAlteco));
    logger.info(`RECONCILE INIT: Electra/client has ${dfClient.length} rows`);
    logger.debug('RECONCILE INIT: Electra/client rows:', JSON.stringify(dfClient));

    this.merged = outerJoin(dfAlteco, dfClient, 'meter_number');
    this.matched = this.merged.filter((j) => j._merge === 'both');
    logger.info(
      `RECONCILE INIT: meter_number merge -> ${this.matched.length} matched, ` +
        `${this.merged.filter((j) => j._merge === 'left_only').length} Alteco-only, ` +
        `${this.merged.filter((j) => j._merge === 'right_only').length} Electra-only`
    );
  }

  private addCoverageGap(matchKey: string, value: unknown, clientName: unknown, issue: string): void {
    logger.warn(`COVERAGE GAP: ${matchKey} '${String(value)}' — ${issue}`);
    this.discrepanciesStep0.push({ 'Match Key': matchKey, Value: value, 'Client Name': clientName, Issue: issue });
  }

  /**
   * Logs a meter number that appears more than once on one side -- e.g. a
   * physical meter reused/reassigned to a different customer -- so the root
   * cause of any resulting cross-paired Step 1/2 noise is visible in the
   * terminal. This is a data-quality issue, not a coverage gap (the meter
   * isn't missing from either side), so it's deliberately kept out of the
   * Meter Coverage table itself.
   */
  private detectDuplicateMeters(rows: StandardRow[], sideLabel: string): void {
    const counts = new Map<string, StandardRow[]>();
    for (const row of rows) {
      const meter = row.meter_number as string | null;
      if (meter === null || meter === undefined) continue;
      if (!counts.has(meter)) counts.set(meter, []);
      counts.get(meter)!.push(row);
    }
    for (const [meter, matchingRows] of counts.entries()) {
      if (matchingRows.length <= 1) continue;
      const customerIds = Array.from(
        new Set(matchingRows.map((r) => r.customer_id).filter((v): v is string => v !== null && v !== undefined).map(String))
      );
      const names = customerIds.length > 0 ? customerIds.join(', ') : null;
      logger.warn(`DUPLICATE METER: '${meter}' appears ${matchingRows.length} times in ${sideLabel} (customers: ${names})`);
    }
  }

  runStep0Coverage(): void {
    logger.info('STEP 0: starting coverage check');

    this.detectDuplicateMeters(this.dfAlteco, 'Alteco');
    this.detectDuplicateMeters(this.dfClient, 'Electra');

    const altecoOnly = this.merged.filter((j) => j._merge === 'left_only');
    const clientOnly = this.merged.filter((j) => j._merge === 'right_only');

    for (const j of altecoOnly) {
      this.addCoverageGap('Meter Number', j.left!.meter_number, j.left!.customer_name, 'Missing from Electra');
    }
    for (const j of clientOnly) {
      this.addCoverageGap('Meter Number', j.right!.meter_number, j.right!.customer_name, 'Missing from Alteco');
    }

    const altecoCustomers = dedupeByCustomerId(this.dfAlteco);
    const clientCustomers = dedupeByCustomerId(this.dfClient);
    logger.debug(
      `STEP 0: customer-level coverage — ${altecoCustomers.length} distinct Alteco customer_id(s), ` +
        `${clientCustomers.length} distinct Electra customer_id(s)`
    );
    const customerJoin = outerJoin(altecoCustomers, clientCustomers, 'customer_id');
    for (const j of customerJoin) {
      if (j._merge === 'left_only') {
        this.addCoverageGap('Customer ID', j.left!.customer_id, j.left!.customer_name, 'Missing from Electra');
      } else if (j._merge === 'right_only') {
        this.addCoverageGap('Customer ID', j.right!.customer_id, j.right!.customer_name, 'Missing from Alteco');
      }
    }

    logger.info(`STEP 0: finished — ${this.discrepanciesStep0.length} coverage issues found`);
  }

  runStep1Metadata(): void {
    logger.info(`STEP 1: starting metadata check on ${this.matched.length} matched meter(s)`);

    for (const j of this.matched) {
      const meterNum = j.key;
      const clientName = j.left!.customer_name;

      for (const [field, [nameEn, nameHe]] of STEP1_FIELDS) {
        let valAlteco: unknown = (j.left as Record<string, unknown>)[field];
        let valClient: unknown = (j.right as Record<string, unknown>)[field];

        if (field === 'billing_month' && valAlteco !== null && valAlteco !== undefined) {
          try {
            valAlteco = formatDate(valAlteco, 'yyyy-MM');
          } catch {
            // keep original on parse failure
          }
        }

        if (field === 'contract_start_date' && valAlteco !== null && valAlteco !== undefined && valClient !== null && valClient !== undefined) {
          try {
            valAlteco = formatDate(valAlteco, 'yyyy-MM-dd');
            valClient = formatDate(valClient, 'yyyy-MM-dd');
          } catch {
            // whichever succeeded before the failure stays reformatted, matching
            // the Python engine's line-by-line try/except exactly
          }
        }

        const normAlteco = normalizeForComparison(valAlteco);
        const normClient = normalizeForComparison(valClient);

        if (normAlteco === '' && normClient === '') {
          logger.debug(`STEP 1: Meter '${meterNum}' field '${nameEn}' — both sides blank, skipped`);
          continue;
        }

        let isMismatch = false;
        if (normAlteco === '' || normClient === '') {
          isMismatch = true;
        } else if (NUMERIC_STRICT_FIELDS.has(field)) {
          const numAlteco = parseNumeric(valAlteco);
          const numClient = parseNumeric(valClient);
          if (numAlteco !== null && numClient !== null) {
            if (numAlteco !== numClient) isMismatch = true;
          } else if (normAlteco !== normClient) {
            isMismatch = true;
          }
        } else if (field === 'customer_name') {
          if (!arraysEqual(splitWords(normAlteco), splitWords(normClient))) isMismatch = true;
        } else if (normAlteco !== normClient) {
          isMismatch = true;
        }

        logger.debug(
          `STEP 1: Meter '${meterNum}' field '${nameEn}' — Alteco=${JSON.stringify(valAlteco)} Client=${JSON.stringify(valClient)} -> ${
            isMismatch ? 'MISMATCH' : 'match'
          }`
        );

        if (isMismatch) {
          logger.warn(`PHASE 1 MISMATCH for Meter '${meterNum}' on '${nameEn}'`);
          this.discrepanciesStep1.push({
            'Meter Number': meterNum,
            'Client Name': clientName,
            'Mismatched Field': nameEn,
            'Original Field (Hebrew)': nameHe,
            'Alteco Value': valAlteco,
            'Client Value': valClient,
          });
        }
      }
    }

    logger.info(`STEP 1: finished — ${this.discrepanciesStep1.length} mismatches found`);
  }

  runStep2Consumption(): void {
    logger.info(`STEP 2: starting consumption check on ${this.matched.length} matched meter(s)`);

    for (const j of this.matched) {
      const meterNum = j.key;
      const clientName = j.left!.customer_name;

      for (const [field, [nameEn, nameHe]] of STEP2_FIELDS) {
        const valAlteco: unknown = (j.left as Record<string, unknown>)[field];
        const valClient: unknown = (j.right as Record<string, unknown>)[field];

        const normAlteco = normalizeForComparison(valAlteco);
        const normClient = normalizeForComparison(valClient);

        if (normAlteco === '' && normClient === '') {
          logger.debug(`STEP 2: Meter '${meterNum}' field '${nameEn}' — both sides blank, skipped`);
          continue;
        }

        let isMismatch = false;
        let outAlteco: unknown = valAlteco;
        let outClient: unknown = valClient;

        if (normAlteco === '' || normClient === '') {
          isMismatch = true;
        } else {
          const numAlteco = parseNumeric(valAlteco);
          const numClient = parseNumeric(valClient);
          if (numAlteco !== null && numClient !== null) {
            outAlteco = Math.round(numAlteco * 100) / 100;
            outClient = Math.round(numClient * 100) / 100;
            if (Math.abs(numAlteco - numClient) > STEP2_TOLERANCE) isMismatch = true;
          } else {
            logger.error(`Invalid consumption data type for Meter '${meterNum}'`);
            isMismatch = true;
          }
        }

        logger.debug(
          `STEP 2: Meter '${meterNum}' field '${nameEn}' — Alteco=${JSON.stringify(outAlteco)} Client=${JSON.stringify(outClient)} -> ${
            isMismatch ? 'MISMATCH' : 'match'
          }`
        );

        if (isMismatch) {
          logger.warn(`PHASE 2 MISMATCH for Meter '${meterNum}' on '${nameEn}'`);
          this.discrepanciesStep2.push({
            'Meter Number': meterNum,
            'Client Name': clientName,
            'Mismatched Field': nameEn,
            'Original Field (Hebrew)': nameHe,
            'Alteco Value': outAlteco,
            'Client Value': outClient,
          });
        }
      }
    }

    logger.info(`STEP 2: finished — ${this.discrepanciesStep2.length} mismatches found`);
  }

  /**
   * Compares customer-level financial totals. Electra's DRFT is naturally
   * per-customer (summed there at load time); Alteco is per-meter, so a
   * customer with multiple meters needs those meters summed here before the
   * two sides can be compared fairly.
   */
  runStep3Financials(): void {
    const altecoByCustomer = aggregateByCustomer(this.dfAlteco);
    const clientByCustomer = aggregateByCustomer(this.dfClient);

    const merged = outerJoin(
      altecoByCustomer as unknown as Array<Record<string, unknown>>,
      clientByCustomer as unknown as Array<Record<string, unknown>>,
      'customer_id'
    ).filter((j) => j._merge === 'both');

    logger.info(
      `STEP 3: starting financial check — ${altecoByCustomer.length} Alteco customer(s), ` +
        `${clientByCustomer.length} Electra customer(s), ${merged.length} matched by customer_id`
    );

    for (const j of merged) {
      const customerId = j.key;
      const left = j.left as unknown as CustomerAggregate;
      const right = j.right as unknown as CustomerAggregate;
      const clientName = left.customer_name;

      for (const [field, [nameEn, nameHe]] of STEP3_FIELDS) {
        const numAlteco = (left as unknown as Record<string, number>)[field];
        const numClient = (right as unknown as Record<string, number>)[field];
        const isMismatch = Math.abs(numAlteco - numClient) > STEP3_TOLERANCE;

        logger.debug(
          `STEP 3: Customer '${customerId}' field '${nameEn}' — Alteco=${numAlteco.toFixed(2)} Client=${numClient.toFixed(2)} -> ${
            isMismatch ? 'MISMATCH' : 'match'
          }`
        );

        if (isMismatch) {
          logger.warn(`PHASE 3 MISMATCH for Customer '${customerId}' on '${nameEn}'`);
          this.discrepanciesStep3.push({
            'Customer ID': customerId,
            'Client Name': clientName,
            'Mismatched Field': nameEn,
            'Original Field (Hebrew)': nameHe,
            'Alteco Value': Math.round(numAlteco * 100) / 100,
            'Client Value': Math.round(numClient * 100) / 100,
          });
        }
      }
    }

    logger.info(`STEP 3: finished — ${this.discrepanciesStep3.length} mismatches found`);
  }

  runAllSteps(): ReconciliationResults {
    this.discrepanciesStep0 = [];
    this.discrepanciesStep1 = [];
    this.discrepanciesStep2 = [];
    this.discrepanciesStep3 = [];

    logger.info('RECONCILE: running all steps');
    this.runStep0Coverage();
    this.runStep1Metadata();
    this.runStep2Consumption();
    this.runStep3Financials();
    logger.info(
      `RECONCILE: complete — step0=${this.discrepanciesStep0.length} step1=${this.discrepanciesStep1.length} ` +
        `step2=${this.discrepanciesStep2.length} step3=${this.discrepanciesStep3.length}`
    );

    return {
      step0: this.discrepanciesStep0,
      step1: this.discrepanciesStep1,
      step2: this.discrepanciesStep2,
      step3: this.discrepanciesStep3,
    };
  }
}
