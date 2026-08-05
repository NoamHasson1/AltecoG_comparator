// Minimal structured logger mirroring the Python backend's logging setup:
// full pipeline visibility (every loaded sheet, every field comparison) at
// debug level by default. Drop LOG_LEVEL to "info" in the environment if
// that's too verbose on a large real file -- same tradeoff as before.
const LEVELS = ['error', 'warn', 'info', 'debug'] as const;
type Level = (typeof LEVELS)[number];

const configuredLevel = (process.env.LOG_LEVEL ?? 'debug').toLowerCase() as Level;
const configuredIndex = LEVELS.includes(configuredLevel) ? LEVELS.indexOf(configuredLevel) : LEVELS.indexOf('debug');

function shouldLog(level: Level): boolean {
  return LEVELS.indexOf(level) <= configuredIndex;
}

export function createLogger(name: string) {
  const prefix = (level: string) => `${new Date().toISOString()} [${level.toUpperCase()}] ${name}:`;
  return {
    error: (...args: unknown[]) => shouldLog('error') && console.error(prefix('error'), ...args),
    warn: (...args: unknown[]) => shouldLog('warn') && console.warn(prefix('warn'), ...args),
    info: (...args: unknown[]) => shouldLog('info') && console.info(prefix('info'), ...args),
    debug: (...args: unknown[]) => shouldLog('debug') && console.debug(prefix('debug'), ...args),
  };
}
