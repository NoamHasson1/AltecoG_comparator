import fs from 'node:fs';

// The Jinja2 template only ever used url_for('static', path=...) to resolve
// static asset URLs -- there's no real templating logic beyond that, so a
// plain string substitution replaces the one Python-specific piece rather
// than pulling in a full template engine dependency for it.
const URL_FOR_STATIC_PATTERN = /\{\{\s*url_for\('static',\s*path='([^']*)'\)\s*\}\}/g;

export function renderIndexHtml(templatePath: string): string {
  const raw = fs.readFileSync(templatePath, 'utf-8');
  return raw.replace(URL_FOR_STATIC_PATTERN, (_match, staticPath: string) => `/static/${staticPath}`);
}
