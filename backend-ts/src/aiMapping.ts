import Anthropic, {
  APIConnectionError,
  APIError,
  AuthenticationError,
  PermissionDeniedError,
  RateLimitError,
} from '@anthropic-ai/sdk';

const SUGGESTION_MODEL = 'claude-haiku-4-5';

// Keep in sync with DIRECT_FIELDS in frontend/static/main.js -- these are the
// only fields an AI suggestion is scoped to (calculated fields are excluded).
const DIRECT_FIELD_LABELS: Record<string, string> = {
  billing_month: 'Billing Month',
  customer_id: 'Customer ID',
  customer_name: 'Customer Name',
  tax_id: 'Customer Tax ID',
  iec_contract: 'Electricity Contract Number',
  meter_number: 'Meter Number',
  voltage: 'Voltage',
  tou: 'Energy Consumption (time-of-use / reading type)',
  billing_type: 'Billing Type',
  tariff: 'Tariff',
  fixed_payment: 'Fixed Payment',
  contract_start_date: 'Contract Start Date',
  kva: 'KVA',
};

export interface FieldSuggestion {
  sheet: string;
  column: string;
  reason: string;
}

export type MappingSuggestions = Record<string, FieldSuggestion | null>;

function fieldResultSchema() {
  return {
    anyOf: [
      { type: 'null' },
      {
        type: 'object',
        properties: {
          sheet: { type: 'string' },
          column: { type: 'string' },
          reason: { type: 'string' },
        },
        required: ['sheet', 'column', 'reason'],
        additionalProperties: false,
      },
    ],
  };
}

function buildSchema() {
  const keys = Object.keys(DIRECT_FIELD_LABELS);
  return {
    type: 'object',
    properties: Object.fromEntries(keys.map((key) => [key, fieldResultSchema()])),
    required: keys,
    additionalProperties: false,
  };
}

function buildPrompt(sheets: unknown): string {
  const fieldsDesc = Object.entries(DIRECT_FIELD_LABELS)
    .map(([key, label]) => `- ${key}: ${label}`)
    .join('\n');
  const sheetsJson = JSON.stringify(sheets);
  return `You are matching columns from a client's electricity billing export to a fixed set of target fields.

Target fields (key: description):
${fieldsDesc}

The client file has been inspected and its sheets/columns/sample rows are below as JSON. Each sheet has "name", "columns", and up to 3 "sample_rows".

${sheetsJson}

For each target field, decide whether one column in the file clearly corresponds to it. Only suggest a match when you are reasonably confident based on the column name and/or its sample values. If no column is a good match, return null for that field. Never invent a sheet or column name that isn't in the data above.

For every match, give a one-sentence reason referencing the column name and/or sample values that justified the pick.`;
}

/** Anthropic's SDK puts the readable message at error.error.message; e.message
 * is the full "401 {...}" wrapper. */
function cleanErrorMessage(e: APIError): string {
  const body = e.error as { error?: { message?: string } } | undefined;
  return body?.error?.message ?? e.message;
}

/**
 * Asks Claude to suggest a field_mappings-shaped match for the 13 direct
 * fields.
 *
 * Returns an object keyed by field name, each value either null or
 * {sheet, column, reason}.
 *
 * Throws an Error with a short, user-facing message on any Anthropic API
 * failure (bad key, no credits, rate limit, network) -- the caller surfaces
 * that message directly in the UI rather than a raw stack trace.
 */
export async function suggestFieldMapping(sheets: unknown): Promise<MappingSuggestions> {
  const client = new Anthropic();
  let response;
  try {
    response = await client.messages.create({
      model: SUGGESTION_MODEL,
      max_tokens: 2048,
      output_config: { format: { type: 'json_schema', schema: buildSchema() } },
      messages: [{ role: 'user', content: buildPrompt(sheets) }],
    });
  } catch (e) {
    if (e instanceof AuthenticationError) {
      throw new Error('The Anthropic API key is invalid. Double-check ANTHROPIC_API_KEY in your environment.');
    }
    if (e instanceof PermissionDeniedError) {
      throw new Error("This Anthropic API key doesn't have permission to use this model.");
    }
    if (e instanceof RateLimitError) {
      throw new Error('Anthropic API rate limit reached — try again in a moment.');
    }
    if (e instanceof APIConnectionError) {
      throw new Error('Could not reach the Anthropic API — check your network connection.');
    }
    if (e instanceof APIError) {
      // Covers things like "Your credit balance is too low..." (400) with
      // Anthropic's own message, which is already clear enough to show as-is.
      throw new Error(cleanErrorMessage(e));
    }
    throw e;
  }

  const textBlock = response.content.find((block) => block.type === 'text');
  if (!textBlock) {
    throw new Error('The AI suggestion response contained no text content.');
  }
  return JSON.parse(textBlock.text) as MappingSuggestions;
}
