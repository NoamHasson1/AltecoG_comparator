import logging

import pandas as pd

logger = logging.getLogger(__name__)

# --- STANDARD SCHEMA ---
# This is the unified dictionary that both systems will be mapped to.
STANDARD_SCHEMA = [
    # Step 1: Commercial & Metadata
    "billing_month",
    "customer_id",
    "customer_name",
    "tax_id",
    "iec_contract",
    "meter_number",
    "voltage",
    "tou",
    "billing_type",
    "tariff",
    "fixed_payment",
    "contract_start_date",
    "kva",

    # Step 2: Consumption (kWh)
    "total_kwh",

    # Step 3: Financial Reconciliation
    "total_payment",
    "kva_fixed_charge",
    "supply_fixed_charge",
    "distribution_fixed_charge"
]

def normalize_id_value(value):
    """
    Cleans a single identifier value read from Excel. Most importantly, undoes
    the float artifact Excel/pandas introduces for numeric-looking IDs: a
    blank cell anywhere in an otherwise-integer ID column forces the whole
    column to float64 (pandas can't represent NaN as int64), so "377007686"
    round-trips as 377007686.0 — a naive str() would then stringify it as
    "377007686.0" and silently fail to match the clean "377007686" string on
    the other side of the reconciliation.

    A genuinely blank/NaN cell returns None — not the literal string "nan",
    which would otherwise look like a real (and mismatching) ID value.
    """
    if pd.isna(value):
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def load_alteco_data(file_path):
    """
    Loads Alteco data and standardizes column names to the generic schema.
    """
    logger.info("ALTECO LOAD: reading sheet 'חשבונית חוזה' from %s", file_path)
    df = pd.read_excel(file_path, sheet_name="חשבונית חוזה")
    logger.info("ALTECO LOAD: read %d rows, %d columns", len(df), len(df.columns))

    # Map Alteco specific Hebrew columns to generic English columns (Includes Step 1 & 2)
    rename_map = {
        # Step 1: Metadata
        "חודש חיוב": "billing_month",
        "מספר לקוח": "customer_id",
        "שם לקוח": "customer_name",
        "ח.פ לקוח": "tax_id",
        "מספר חוזה חח״י": "iec_contract",
        "מספר מונה": "meter_number",
        "מתח": "voltage",
        "תעו״ז": "tou",
        "סוג חיוב": "billing_type",
        "תעריף": "tariff",
        "תשלום קבוע": "fixed_payment",
        "תאריך התחלת החוזה": "contract_start_date",
        "KVA": "kva",

        # Step 2: Consumption
        "סה״כ צריכה קוט״ש": "total_kwh",

        # Step 3: Financial Reconciliation
        "סה״כ לתשלום (כולל מע״מ) ₪": "total_payment",
        "חיוב קבוע KVA ₪": "kva_fixed_charge",
        "חיוב קבוע אספקה ₪": "supply_fixed_charge",
        "חיוב קבוע חלוקה ₪": "distribution_fixed_charge"
    }
    df = df.rename(columns=rename_map)

    # Loudly flag any expected Alteco column that wasn't found — a rename-map
    # mismatch (e.g. a stray extra space in the real file's header) would
    # otherwise leave that field silently all-None/0 with no indication
    # anything was wrong. This is exactly the class of bug that made Supply
    # Fixed Charge look like it was always 0 in the Alteco file.
    reverse_map = {}
    for hebrew_col, target in rename_map.items():
        reverse_map.setdefault(target, hebrew_col)
    for col in STANDARD_SCHEMA:
        if col not in df.columns and col in reverse_map:
            logger.warning(
                "ALTECO COLUMN NOT FOUND: expected a column named exactly %r for '%s', "
                "but no such column exists in the uploaded file. This field will be "
                "entirely blank/zero in the results — check for a spelling or spacing "
                "difference in the Alteco export's header.",
                reverse_map[col], col,
            )

    # Ensure all STANDARD_SCHEMA columns exist (fill with None if missing).
    # Inserted all at once via concat rather than one `df[col] = None` at a
    # time, which fragments the DataFrame and triggers a PerformanceWarning.
    missing_cols = [col for col in STANDARD_SCHEMA if col not in df.columns]
    if missing_cols:
        df = pd.concat([df, pd.DataFrame(None, index=df.index, columns=missing_cols)], axis=1)

    # Clean string identifiers
    for col in ["meter_number", "customer_id"]:
        if col in df.columns:
            df[col] = df[col].map(normalize_id_value)

    result = df[STANDARD_SCHEMA]
    logger.debug("ALTECO LOAD: final DataFrame (%d rows):\n%s", len(result), result.to_string())
    return result
