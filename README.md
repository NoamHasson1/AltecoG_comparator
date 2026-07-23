# Alteco Billing Comparison (Reconciliation Engine)

**Project Goal:** A financial/billing reconciliation ETL tool that compares electricity billing data between a source provider and a billing system ("Alteco").
**Tech Stack:** Python 3.x, FastAPI, Pandas, Vanilla JavaScript, HTML/CSS.
**Core Workflow:**
1. Extract data from two distinct Excel formats.
2. Transform and map both to a unified `STANDARD_SCHEMA`.
3. Load them into a `ReconciliationEngine`.
4. Run strict business rules (Metadata matching, Consumption aggregation with tolerance).
5. Output JSON arrays of discrepancies for a frontend UI to display.
