export type MergeType = 'both' | 'left_only' | 'right_only';

export interface JoinedRow<L, R> {
  key: string;
  _merge: MergeType;
  left: L | null;
  right: R | null;
}

/**
 * Outer join replicating pandas' pd.merge(..., how='outer') behavior:
 * - Duplicate keys on both sides produce every combination (a cross
 *   product), not just a 1:1 pairing -- this is a deliberate, tested
 *   "known limitation" carried over from the Python engine (see
 *   test_duplicate_meter_number_produces_cross_paired_rows).
 * - A null/undefined key never matches anything, not even another
 *   null-keyed row on the other side (mirrors pandas' NaN-never-matches
 *   join-key semantics) -- it always surfaces as left_only/right_only.
 */
export function outerJoin<L extends Record<string, unknown>, R extends Record<string, unknown>>(
  leftRows: L[],
  rightRows: R[],
  keyField: string
): JoinedRow<L, R>[] {
  const leftByKey = new Map<string, L[]>();
  const leftUnkeyed: L[] = [];
  for (const row of leftRows) {
    const key = row[keyField];
    if (key === null || key === undefined) {
      leftUnkeyed.push(row);
      continue;
    }
    const k = String(key);
    if (!leftByKey.has(k)) leftByKey.set(k, []);
    leftByKey.get(k)!.push(row);
  }

  const rightByKey = new Map<string, R[]>();
  const rightUnkeyed: R[] = [];
  for (const row of rightRows) {
    const key = row[keyField];
    if (key === null || key === undefined) {
      rightUnkeyed.push(row);
      continue;
    }
    const k = String(key);
    if (!rightByKey.has(k)) rightByKey.set(k, []);
    rightByKey.get(k)!.push(row);
  }

  const results: JoinedRow<L, R>[] = [];
  const allKeys = new Set([...leftByKey.keys(), ...rightByKey.keys()]);
  for (const key of allKeys) {
    const lefts = leftByKey.get(key);
    const rights = rightByKey.get(key);
    if (lefts && rights) {
      for (const l of lefts) {
        for (const r of rights) {
          results.push({ key, _merge: 'both', left: l, right: r });
        }
      }
    } else if (lefts) {
      for (const l of lefts) results.push({ key, _merge: 'left_only', left: l, right: null });
    } else if (rights) {
      for (const r of rights) results.push({ key, _merge: 'right_only', left: null, right: r });
    }
  }

  for (const l of leftUnkeyed) results.push({ key: '', _merge: 'left_only', left: l, right: null });
  for (const r of rightUnkeyed) results.push({ key: '', _merge: 'right_only', left: null, right: r });

  return results;
}
