import { describe, it, expect, beforeAll, afterAll, beforeEach } from 'vitest';
import { MongoMemoryServer } from 'mongodb-memory-server';
import {
  listMappingNames,
  getMapping,
  saveMapping,
  deleteMapping,
  deleteAllMappings,
  _resetConnectionForTests,
} from '../src/mappingStore.js';

let mongod: MongoMemoryServer;

beforeAll(async () => {
  mongod = await MongoMemoryServer.create();
  process.env.MONGODB_URI = mongod.getUri('altego_test');
});

afterAll(async () => {
  await _resetConnectionForTests();
  await mongod.stop();
});

beforeEach(async () => {
  // Fresh connection per test, and clear everything except the bundled
  // default -- mirrors the isolation the Python test suite got by pointing
  // at a fresh Docker Postgres, without wiping out the seed itself.
  await _resetConnectionForTests();
  await deleteAllMappings('electra_default');
});

describe('mappingStore', () => {
  it('seeds the bundled default mapping on first use', async () => {
    const names = await listMappingNames();
    expect(names).toContain('electra_default');
    const config = await getMapping('electra_default');
    expect(config).not.toBeNull();
    expect((config as Record<string, unknown>).field_mappings).toBeDefined();
  });

  it('saves and round-trips a mapping', async () => {
    const config = { field_mappings: { customer_id: { sheet: 'S', column: 'C' } } };
    await saveMapping('test_roundtrip', config);
    expect(await getMapping('test_roundtrip')).toEqual(config);
  });

  it('overwrites an existing mapping on save', async () => {
    await saveMapping('test_overwrite', { a: 1 });
    await saveMapping('test_overwrite', { a: 2 });
    expect(await getMapping('test_overwrite')).toEqual({ a: 2 });
  });

  it('returns null for a mapping that does not exist', async () => {
    expect(await getMapping('does_not_exist_at_all')).toBeNull();
  });

  it('lists a saved mapping by name', async () => {
    await saveMapping('test_list_me', { a: 1 });
    expect(await listMappingNames()).toContain('test_list_me');
  });

  it('deletes a mapping and reports success', async () => {
    await saveMapping('test_delete_me', { a: 1 });
    expect(await deleteMapping('test_delete_me')).toBe(true);
    expect(await getMapping('test_delete_me')).toBeNull();
  });

  it('reports false when deleting a mapping that does not exist', async () => {
    expect(await deleteMapping('never_existed_here')).toBe(false);
  });

  it('deletes all mappings except the protected one', async () => {
    await saveMapping('test_drop_me', { a: 1 });
    await deleteAllMappings('electra_default');
    expect(await getMapping('test_drop_me')).toBeNull();
    expect(await getMapping('electra_default')).not.toBeNull();
  });
});
