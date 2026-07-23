import pandas as pd

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

def load_alteco_data(file_path):
    """
    Loads Alteco data and standardizes column names to the generic schema.
    """
    df = pd.read_excel(file_path, sheet_name="חשבונית חוזה")
    
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
        "חיוב קבוע אספקה  ₪": "supply_fixed_charge",
        "חיוב קבוע חלוקה ₪": "distribution_fixed_charge"
    }
    df = df.rename(columns=rename_map)
    
    # Ensure all STANDARD_SCHEMA columns exist (fill with None if missing)
    for col in STANDARD_SCHEMA:
        if col not in df.columns:
            df[col] = None
            
    # Clean string identifiers
    for col in ["meter_number", "customer_id"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
            
    return df[STANDARD_SCHEMA]