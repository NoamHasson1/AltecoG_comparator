import { describe, it, expect } from 'vitest';
import { suggestFieldMapping } from '../src/aiMapping.js';

// No existing Python test for this module either (it was never unit-tested
// there, since it's a real paid external API). This test only exercises the
// error-cleaning path against a deliberately invalid key -- that fails at
// the authentication layer before any model usage is billed, so it's free
// and deterministic, unlike a real successful completion would be.
describe('suggestFieldMapping', () => {
  it('surfaces a clean, user-facing message for an invalid API key rather than the raw SDK wrapper', async () => {
    const original = process.env.ANTHROPIC_API_KEY;
    process.env.ANTHROPIC_API_KEY = 'sk-ant-invalid-key-for-testing';
    try {
      await expect(suggestFieldMapping({ sheets: [] })).rejects.toThrow(/invalid|API key/i);
    } finally {
      if (original === undefined) delete process.env.ANTHROPIC_API_KEY;
      else process.env.ANTHROPIC_API_KEY = original;
    }
  });
});
