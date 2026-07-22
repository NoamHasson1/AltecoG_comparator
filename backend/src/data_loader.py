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
    "offpeak_kwh",
    "peak_kwh"
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
        "צריכה בשפל קוט״ש": "offpeak_kwh",
        "צריכה בפסגה קוט״ש": "peak_kwh"
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


# --- ELECTRA HELPER FUNCTIONS ---

def _extract_electra_metadata(df_meta, df_drft):
    """
    Helper Function (Step 1): Extracts and normalizes metadata and commercial terms.
    """
    # 1. Filter out dismantled meters immediately
    if "סטטוס מתקן" in df_meta.columns:
        df_meta = df_meta[df_meta["סטטוס מתקן"] == "פעיל"]

    # 2. Extract billing month and days from DRFT
    df_drft['derived_month'] = pd.to_datetime(df_drft['draftDate']).dt.strftime('%Y-%m')

    # Compress multiple billing rows to one summary metadata row per Customer ID
    drft_summary = df_drft.groupby('AccountExtID').agg({
        'derived_month': 'first',
        'AccountName': 'first'
    }).reset_index()

    # 3. Standardize IDs before internal merge
    df_meta['מספר לקוח'] = df_meta['מספר לקוח'].astype(str).str.strip()
    drft_summary['AccountExtID'] = drft_summary['AccountExtID'].astype(str).str.strip()

    # 4. Merge internal metadata
    merged_metadata = pd.merge(df_meta, drft_summary, left_on="מספר לקוח", right_on="AccountExtID", how="left")

    # 5. Map to English schema
    rename_map = {
        "derived_month": "billing_month",
        "מספר לקוח": "customer_id",
        "AccountName": "customer_name",
        "ת.ז./ח.פ.": "tax_id",
        'מספר חח"י': "iec_contract",
        "מספר מונה": "meter_number",
        "מתח": "voltage",
        "קבוע": "fixed_payment",
        "תאריך הצטרפות": "contract_start_date",
        "KVA": "kva"
    }
    merged_metadata = merged_metadata.rename(columns=rename_map)
    
    return merged_metadata


def _calculate_electra_consumption(df_drft):
    """
    Helper Function (Step 2): Filters DRFT for 'Detail usage' and aggregates kWh quantities.
    """
    # 1. Isolate only the actual electricity usage lines (ignore fixed payments/KVA rows)
    usage_df = df_drft[df_drft['DraftLineType'] == 'Detail usage'].copy()
    usage_df['AccountExtID'] = usage_df['AccountExtID'].astype(str).str.strip()
    
    # Ensure Quantity is numeric (fallback to 0 if text/empty)
    usage_df['Quantity'] = pd.to_numeric(usage_df['Quantity'], errors='coerce').fillna(0)
    
    # 2. CALCULATE TOTAL KWH: Sum all quantity rows per customer
    total_kwh = usage_df.groupby('AccountExtID')['Quantity'].sum().reset_index()
    total_kwh = total_kwh.rename(columns={'Quantity': 'total_kwh'})
    
    # 3. CALCULATE OFF-PEAK KWH: Look for keywords in the description
    offpeak_df = usage_df[usage_df['draftLineDescription'].str.contains('לילה|שפל|סופש|סופ״ש', na=False, regex=True)]
    offpeak_kwh = offpeak_df.groupby('AccountExtID')['Quantity'].sum().reset_index()
    offpeak_kwh = offpeak_kwh.rename(columns={'Quantity': 'offpeak_kwh'})
    
    # 4. CALCULATE PEAK KWH: Look for peak keywords
    peak_df = usage_df[usage_df['draftLineDescription'].str.contains('פסגה|יום', na=False, regex=True)]
    peak_kwh = peak_df.groupby('AccountExtID')['Quantity'].sum().reset_index()
    peak_kwh = peak_kwh.rename(columns={'Quantity': 'peak_kwh'})
    
    # 5. Merge all consumption calculations together
    consumption_summary = total_kwh
    consumption_summary = pd.merge(consumption_summary, offpeak_kwh, on='AccountExtID', how='left')
    consumption_summary = pd.merge(consumption_summary, peak_kwh, on='AccountExtID', how='left')
    
    # Rename key column to match our schema for the final merge
    consumption_summary = consumption_summary.rename(columns={'AccountExtID': 'customer_id'})
    
    return consumption_summary


# --- MAIN LOADER FUNCTION ---

def load_electra_data(file_path):
    """
    Main loader for Electra: Orchestrates metadata extraction and consumption calculations.
    """
    # Read all sheets efficiently
    all_sheets = pd.read_excel(file_path, sheet_name=None)
    df_meta = all_sheets.get("מצבת לקוחות", pd.DataFrame())
    df_drft = all_sheets.get("DRFT", pd.DataFrame())

    # --- Phase 1: Get Metadata ---
    metadata_df = _extract_electra_metadata(df_meta, df_drft)
    
    # --- Phase 2: Get Calculated Consumption ---
    consumption_df = _calculate_electra_consumption(df_drft)
    
    # --- Join the data together! ---
    # We do a left join so metadata exists even if a customer had 0 consumption this month
    electra_unified = pd.merge(metadata_df, consumption_df, on="customer_id", how="left")

    # Ensure all STANDARD_SCHEMA columns exist (fill with None if missing)
    for col in STANDARD_SCHEMA:
        if col not in electra_unified.columns:
            electra_unified[col] = None

    # Final sweep to clean string identifiers
    for col in ["meter_number", "customer_id"]:
        if col in electra_unified.columns:
            electra_unified[col] = electra_unified[col].astype(str).str.strip()

    return electra_unified[STANDARD_SCHEMA]