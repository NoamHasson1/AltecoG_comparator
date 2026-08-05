import { Collection, Document, MongoClient } from 'mongodb';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createLogger } from './logger.js';

const logger = createLogger('mappingStore');

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Bundled preset shipped in the repo -- seeded into the collection once so a
// fresh database starts with the same default mapping the app has always
// shipped.
const DEFAULT_MAPPING_NAME = 'electra_default';
const DEFAULT_MAPPING_PATH = path.join(__dirname, '..', 'mappings', `${DEFAULT_MAPPING_NAME}.json`);

interface MappingDocument extends Document {
  name: string;
  config: Record<string, unknown>;
  updatedAt: Date;
}

// A single MongoClient (with its own internal connection pool) is reused for
// the life of the process -- the idiomatic pattern for MongoDB in a
// long-running Node server, unlike the "new connection per call" pattern the
// Postgres version used specifically for serverless/pooled Postgres.
let cachedClient: MongoClient | null = null;
let indexEnsured = false;

async function getCollection(): Promise<Collection<MappingDocument>> {
  const uri = process.env.MONGODB_URI;
  if (!uri) {
    throw new Error(
      'MONGODB_URI is not set — saved-mapping storage is not configured. Set it to your MongoDB connection string.'
    );
  }
  if (!cachedClient) {
    cachedClient = new MongoClient(uri);
    await cachedClient.connect();
  }
  const collection = cachedClient.db().collection<MappingDocument>('mappings');
  if (!indexEnsured) {
    await collection.createIndex({ name: 1 }, { unique: true });
    await seedDefaultMapping(collection);
    indexEnsured = true;
  }
  return collection;
}

async function seedDefaultMapping(collection: Collection<MappingDocument>): Promise<void> {
  if (!fs.existsSync(DEFAULT_MAPPING_PATH)) return;
  const config = JSON.parse(fs.readFileSync(DEFAULT_MAPPING_PATH, 'utf-8'));
  await collection.updateOne(
    { name: DEFAULT_MAPPING_NAME },
    { $setOnInsert: { name: DEFAULT_MAPPING_NAME, config, updatedAt: new Date() } },
    { upsert: true }
  );
  logger.info(`MAPPING STORE: ensured bundled default mapping '${DEFAULT_MAPPING_NAME}' exists (no-op if already present)`);
}

export async function listMappingNames(): Promise<string[]> {
  const collection = await getCollection();
  const docs = await collection
    .find({}, { projection: { name: 1 } })
    .sort({ name: 1 })
    .toArray();
  return docs.map((d) => d.name);
}

/** Returns the mapping's config, or null if no mapping exists under that name. */
export async function getMapping(name: string): Promise<Record<string, unknown> | null> {
  const collection = await getCollection();
  const doc = await collection.findOne({ name });
  return doc ? doc.config : null;
}

/** Inserts or overwrites (upsert) the mapping under the given name. */
export async function saveMapping(name: string, config: Record<string, unknown>): Promise<void> {
  const collection = await getCollection();
  await collection.updateOne({ name }, { $set: { name, config, updatedAt: new Date() } }, { upsert: true });
}

/** Deletes a mapping by name. Returns true if a document was deleted, false if it didn't exist. */
export async function deleteMapping(name: string): Promise<boolean> {
  const collection = await getCollection();
  const result = await collection.deleteOne({ name });
  return result.deletedCount > 0;
}

/** Deletes every saved mapping except the given (protected) name. */
export async function deleteAllMappings(exceptName: string): Promise<void> {
  const collection = await getCollection();
  await collection.deleteMany({ name: { $ne: exceptName } });
}

/** Test-only escape hatch: forces a fresh connection on the next call, so
 * each test file can point at its own throwaway in-memory MongoDB instance. */
export async function _resetConnectionForTests(): Promise<void> {
  if (cachedClient) {
    await cachedClient.close();
    cachedClient = null;
  }
  indexEnsured = false;
}
