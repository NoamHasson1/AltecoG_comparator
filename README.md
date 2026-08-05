# Alteco Billing Comparison (Reconciliation Engine)

**Project Goal:** A financial/billing reconciliation tool that compares electricity billing data between a client's export and Alteco's own billing system.
**Tech Stack:** TypeScript, Express, MongoDB, Vanilla JavaScript, HTML/CSS.
**Core Workflow:**
1. Extract data from two distinct Excel formats (a fixed Alteco format, and a client format described by a user-configured field mapping).
2. Transform and map both to a unified standard schema.
3. Load them into a `ReconciliationEngine`.
4. Run strict business rules (Metadata matching, Consumption/Financial comparison with tolerance).
5. Output JSON arrays of discrepancies for a frontend UI to display, and an exportable `.xlsx` report.

## Project layout

- `backend-ts/` — the Express/TypeScript backend and its test suite.
- `frontend/` — the vanilla JS/HTML/CSS UI, served by the backend.

## Getting started

```bash
cd backend-ts
npm install
cp .env.example .env   # fill in ANTHROPIC_API_KEY and MONGODB_URI
npm run dev
```

Then open `http://127.0.0.1:5001`. See `backend-ts/.env.example` for what each environment variable does and how to get a local MongoDB running.

Run the test suite with `npm test` (from `backend-ts/`).
