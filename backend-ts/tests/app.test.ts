import { describe, it, expect, beforeAll, afterAll, beforeEach, afterEach } from 'vitest';
import request from 'supertest';
import { MongoMemoryServer } from 'mongodb-memory-server';
import fs from 'node:fs';
import path from 'node:path';
import { createApp } from '../src/app.js';
import { _resetConnectionForTests, deleteAllMappings } from '../src/mappingStore.js';
import { writeWorkbook, trackTempFiles } from './testFixtures.js';

const MAPPING_PATH = path.resolve(process.cwd(), 'mappings', 'electra_default.json');
const temp = trackTempFiles();
afterEach(() => temp.cleanup());

/** A small, self-contained pair matching the bundled electra_default.json
 * mapping's expected shape (מצבת לקוחות + DRFT sheets) -- deliberately
 * built to reconcile clean (0 mismatches) rather than reproducing any
 * particular real file's data. */
async function writeCleanMatchPair() {
  const altecoFile = temp.track(
    await writeWorkbook([
      {
        name: 'חשבונית חוזה',
        rows: [
          {
            'חודש חיוב': '2026-06',
            'מספר לקוח': 'C1',
            'שם לקוח': 'Client A',
            'ח.פ לקוח': '123456',
            'מספר חוזה חח״י': '999',
            'מספר מונה': 'M-1',
            מתח: 'נמוך',
            'תשלום קבוע': 'LU1PH',
            'תאריך התחלת החוזה': '2024-01-01',
            KVA: 17.32,
            'סה״כ צריכה קוט״ש': 0,
          },
        ],
      },
    ])
  );

  const electraFile = temp.track(
    await writeWorkbook([
      {
        name: 'מצבת לקוחות',
        rows: [
          {
            'מספר מונה': 'M-1',
            'מספר לקוח': 'C1',
            'ת.ז/ח.פ': '123456',
            'מספר חח״י': '999',
            מתח: 'נמוך',
            קבוע: 'LU1PH',
            KVA: 17.32,
            'תאריך הצטרפות': '2024-01-01',
          },
        ],
      },
      {
        name: 'DRFT',
        rows: [{ AccountExtID: 'C1', AccountName: 'Client A', draftDate: '2026-06-15', DraftLineType: 'Detail usage', draftLineDescription: '', Quantity: 0, LineTotalAmount: 0 }],
      },
    ])
  );

  return { altecoFile, electraFile };
}

let mongod: MongoMemoryServer;

beforeAll(async () => {
  mongod = await MongoMemoryServer.create();
  process.env.MONGODB_URI = mongod.getUri('altego_app_test');
});

afterAll(async () => {
  await _resetConnectionForTests();
  await mongod.stop();
});

beforeEach(async () => {
  await _resetConnectionForTests();
  await deleteAllMappings('electra_default');
});

describe('GET /health', () => {
  it('returns ok', async () => {
    const app = createApp();
    const res = await request(app).get('/health');
    expect(res.status).toBe(200);
    expect(res.body).toEqual({ status: 'ok' });
  });
});

describe('GET /', () => {
  it('serves the index page with static paths resolved (no raw Jinja syntax)', async () => {
    const app = createApp();
    const res = await request(app).get('/');
    expect(res.status).toBe(200);
    expect(res.text).toContain('/static/main.js');
    expect(res.text).not.toContain('url_for');
  });
});

describe('GET /static/*', () => {
  it('serves a real static asset', async () => {
    const app = createApp();
    const res = await request(app).get('/static/style.css');
    expect(res.status).toBe(200);
  });
});

describe('mapping CRUD routes', () => {
  it('lists the seeded default mapping', async () => {
    const app = createApp();
    const res = await request(app).get('/mappings');
    expect(res.status).toBe(200);
    expect(res.body).toContain('electra_default');
  });

  it('saves, gets, and deletes a mapping', async () => {
    const app = createApp();
    const config = { field_mappings: { customer_id: { sheet: 'S', column: 'C' } } };

    const saveRes = await request(app).post('/mappings/My Test Mapping').send(config);
    expect(saveRes.status).toBe(200);
    expect(saveRes.body).toEqual({ status: 'saved', name: 'My Test Mapping' });

    const getRes = await request(app).get('/mappings/My Test Mapping');
    expect(getRes.status).toBe(200);
    expect(getRes.body).toEqual(config);

    const deleteRes = await request(app).delete('/mappings/My Test Mapping');
    expect(deleteRes.status).toBe(200);
    expect(deleteRes.body).toEqual({ status: 'deleted', name: 'My Test Mapping' });
  });

  it('404s for a mapping that does not exist', async () => {
    const app = createApp();
    const res = await request(app).get('/mappings/does-not-exist');
    expect(res.status).toBe(404);
    expect(res.body.detail).toMatch(/No saved mapping/);
  });

  it('refuses to delete the protected default mapping', async () => {
    const app = createApp();
    const res = await request(app).delete('/mappings/electra_default');
    expect(res.status).toBe(400);
    expect(res.body.detail).toMatch(/can't be deleted/);
  });

  it('clears all mappings except the protected default', async () => {
    const app = createApp();
    await request(app).post('/mappings/temp-one').send({ a: 1 });
    const res = await request(app).delete('/mappings');
    expect(res.status).toBe(200);
    expect((await request(app).get('/mappings/temp-one')).status).toBe(404);
    expect((await request(app).get('/mappings/electra_default')).status).toBe(200);
  });

  it('400s for an invalid mapping name', async () => {
    const app = createApp();
    const res = await request(app).post('/mappings/%2F%2F%2F').send({ a: 1 });
    expect(res.status).toBe(400);
  });
});

describe('POST /inspect-file', () => {
  it('reads an uploaded file and returns its sheet structure', async () => {
    const app = createApp();
    const { electraFile } = await writeCleanMatchPair();
    const res = await request(app).post('/inspect-file').attach('file', electraFile);
    expect(res.status).toBe(200);
    const sheetNames = res.body.sheets.map((s: { name: string }) => s.name);
    expect(sheetNames).toContain('DRFT');
  });

  it('400s when no file is attached', async () => {
    const app = createApp();
    const res = await request(app).post('/inspect-file');
    expect(res.status).toBe(400);
  });
});

describe('POST /reconcile', () => {
  it('runs a full reconcile using the bundled default mapping end-to-end', async () => {
    const app = createApp();
    const mapping = JSON.parse(fs.readFileSync(MAPPING_PATH, 'utf-8'));
    const { altecoFile, electraFile } = await writeCleanMatchPair();

    const res = await request(app)
      .post('/reconcile')
      .field('mapping', JSON.stringify(mapping))
      .attach('alteco_file', altecoFile)
      .attach('electra_file', electraFile);

    expect(res.status).toBe(200);
    expect(res.body.step0).toHaveLength(0);
    expect(res.body.step1).toHaveLength(0);
    expect(res.body.step2).toHaveLength(0);
    expect(res.body.step3).toHaveLength(0);
  });

  it('500s with a clear message when a file is missing', async () => {
    const app = createApp();
    const res = await request(app).post('/reconcile').field('mapping', '{}');
    expect(res.status).toBe(500);
    expect(res.body.detail).toMatch(/required/);
  });
});

describe('POST /export-discrepancies', () => {
  it('returns a downloadable .xlsx with the right headers', async () => {
    const app = createApp();
    const results = { step0: [], step1: [], step2: [], step3: [] };
    const res = await request(app).post('/export-discrepancies').send(results);
    expect(res.status).toBe(200);
    expect(res.headers['content-type']).toContain('spreadsheetml');
    expect(res.headers['content-disposition']).toContain('attachment');
    expect(res.headers['content-disposition']).toContain('.xlsx');
  });
});
