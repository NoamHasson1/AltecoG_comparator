import express, { Request, Response, NextFunction } from 'express';
import multer from 'multer';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { loadAltecoData } from './dataLoader.js';
import { inspectWorkbook, loadMappedData, MappingConfig } from './dynamicLoader.js';
import { ReconciliationEngine } from './reconciliationEngine.js';
import { buildDiscrepancyWorkbook } from './exportReport.js';
import { suggestFieldMapping } from './aiMapping.js';
import * as mappingStore from './mappingStore.js';
import { HttpError } from './httpError.js';
import { renderIndexHtml } from './renderIndex.js';
import { createLogger } from './logger.js';

const logger = createLogger('app');

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BACKEND_TS_DIR = path.join(__dirname, '..');
const PROJECT_ROOT = path.join(BACKEND_TS_DIR, '..');
const FRONTEND_DIR = path.join(PROJECT_ROOT, 'frontend');

// Bundled preset that main.py (Python CLI) and the test suite depend on
// always existing -- protected from deletion so "Reset All" / single-delete
// can't take it out.
const PROTECTED_MAPPING_NAME = 'electra_default';

const upload = multer({ storage: multer.memoryStorage() });

function cleanMappingName(name: string): string {
  const sanitized = name.replace(/[^A-Za-z0-9_\- ]/g, '').trim();
  if (!sanitized) {
    throw new HttpError(400, 'Invalid mapping name');
  }
  return sanitized;
}

function asyncRoute(handler: (req: Request, res: Response) => Promise<void>) {
  return (req: Request, res: Response, next: NextFunction) => {
    handler(req, res).catch(next);
  };
}

export function createApp() {
  const app = express();
  app.use(express.json());
  app.use('/static', express.static(path.join(FRONTEND_DIR, 'static')));

  app.get('/', (_req, res) => {
    const html = renderIndexHtml(path.join(FRONTEND_DIR, 'templates', 'index.html'));
    res.type('html').send(html);
  });

  app.get('/health', (_req, res) => {
    res.json({ status: 'ok' });
  });

  app.post(
    '/inspect-file',
    upload.single('file'),
    asyncRoute(async (req, res) => {
      if (!req.file) {
        throw new HttpError(400, 'Missing file');
      }
      try {
        const result = await inspectWorkbook(req.file.buffer);
        res.json(result);
      } catch (e) {
        logger.error('inspect-file failed:', e);
        throw new HttpError(500, `Could not read file: ${(e as Error).message}`);
      }
    })
  );

  app.post(
    '/suggest-mapping',
    asyncRoute(async (req, res) => {
      const sheets = req.body?.sheets;
      if (!sheets) {
        throw new HttpError(400, "Missing 'sheets'");
      }
      if (!process.env.ANTHROPIC_API_KEY) {
        throw new HttpError(503, 'AI suggestions are not configured (set ANTHROPIC_API_KEY in .env)');
      }
      try {
        const result = await suggestFieldMapping(sheets);
        res.json(result);
      } catch (e) {
        throw new HttpError(502, `AI suggestion failed: ${(e as Error).message}`);
      }
    })
  );

  app.get(
    '/mappings',
    asyncRoute(async (_req, res) => {
      try {
        res.json(await mappingStore.listMappingNames());
      } catch (e) {
        throw new HttpError(503, (e as Error).message);
      }
    })
  );

  app.get(
    '/mappings/:name',
    asyncRoute(async (req, res) => {
      const cleanName = cleanMappingName(req.params.name as string);
      let config;
      try {
        config = await mappingStore.getMapping(cleanName);
      } catch (e) {
        throw new HttpError(503, (e as Error).message);
      }
      if (config === null) {
        throw new HttpError(404, `No saved mapping named '${req.params.name}'`);
      }
      res.json(config);
    })
  );

  app.post(
    '/mappings/:name',
    asyncRoute(async (req, res) => {
      const cleanName = cleanMappingName(req.params.name as string);
      try {
        await mappingStore.saveMapping(cleanName, req.body);
      } catch (e) {
        throw new HttpError(503, (e as Error).message);
      }
      res.json({ status: 'saved', name: cleanName });
    })
  );

  app.delete(
    '/mappings/:name',
    asyncRoute(async (req, res) => {
      const cleanName = cleanMappingName(req.params.name as string);
      if (cleanName === PROTECTED_MAPPING_NAME) {
        throw new HttpError(400, "The bundled default mapping can't be deleted.");
      }
      let deleted;
      try {
        deleted = await mappingStore.deleteMapping(cleanName);
      } catch (e) {
        throw new HttpError(503, (e as Error).message);
      }
      if (!deleted) {
        throw new HttpError(404, `No saved mapping named '${req.params.name}'`);
      }
      res.json({ status: 'deleted', name: cleanName });
    })
  );

  app.delete(
    '/mappings',
    asyncRoute(async (_req, res) => {
      try {
        await mappingStore.deleteAllMappings(PROTECTED_MAPPING_NAME);
      } catch (e) {
        throw new HttpError(503, (e as Error).message);
      }
      res.json({ status: 'cleared' });
    })
  );

  app.post(
    '/reconcile',
    upload.fields([
      { name: 'alteco_file', maxCount: 1 },
      { name: 'electra_file', maxCount: 1 },
    ]),
    asyncRoute(async (req, res) => {
      const files = req.files as { [field: string]: Express.Multer.File[] } | undefined;
      const altecoFile = files?.alteco_file?.[0];
      const electraFile = files?.electra_file?.[0];
      logger.info(`RECONCILE REQUEST: alteco_file=${altecoFile?.originalname} electra_file=${electraFile?.originalname}`);

      try {
        if (!altecoFile || !electraFile) {
          throw new Error('Both alteco_file and electra_file are required');
        }
        const mappingConfig = JSON.parse(req.body.mapping) as MappingConfig;

        const dfAlteco = await loadAltecoData(altecoFile.buffer);
        const dfElectra = await loadMappedData(electraFile.buffer, mappingConfig);

        const engine = new ReconciliationEngine(dfAlteco, dfElectra);
        const results = engine.runAllSteps();

        logger.info(
          `RECONCILE RESPONSE: step0=${results.step0.length} step1=${results.step1.length} ` +
            `step2=${results.step2.length} step3=${results.step3.length}`
        );

        res.json(results);
      } catch (e) {
        logger.error('RECONCILE FAILED:', e);
        throw new HttpError(500, `An error occurred: ${(e as Error).message}`);
      }
    })
  );

  app.post(
    '/export-discrepancies',
    asyncRoute(async (req, res) => {
      let buffer: Buffer;
      try {
        buffer = await buildDiscrepancyWorkbook(req.body);
      } catch (e) {
        logger.error('export-discrepancies failed:', e);
        throw new HttpError(500, `Could not build report: ${(e as Error).message}`);
      }
      const timestamp = new Date()
        .toISOString()
        .replace(/[-:]/g, '')
        .replace('T', '_')
        .slice(0, 15);
      const filename = `reconciliation_mismatches_${timestamp}.xlsx`;
      res.set({
        'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'Content-Disposition': `attachment; filename="${filename}"`,
      });
      res.send(buffer);
    })
  );

  // Error-handling middleware (must have 4 args for Express to recognize it
  // as such) -- mirrors FastAPI's HTTPException -> {"detail": "..."} shape.
  app.use((err: unknown, _req: Request, res: Response, _next: NextFunction) => {
    if (err instanceof HttpError) {
      res.status(err.status).json({ detail: err.message });
    } else if (err instanceof multer.MulterError) {
      res.status(400).json({ detail: err.message });
    } else {
      logger.error('Unhandled error:', err);
      res.status(500).json({ detail: err instanceof Error ? err.message : 'Internal server error' });
    }
  });

  return app;
}
