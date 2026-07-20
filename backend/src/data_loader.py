import pandas as pd

STANDARD_SCHEMA = [
    "billing_month",
    "billing_days",
    "customer_id",
    "customer_name",
    "tax_id",
    "iec_contract",
    "meter_number",
    "voltage",
    "basic",
    "tou",
    "consumer_type",
    "billing_type",
    "tariff",
    "fixed_payment",
    "contract_start_date",
    "kva"
]

def load_alteco_data(file_path):
    """
    Loads Alteco data and standardizes column names to a generic schema.
    """
    df = pd.read_excel(file_path, sheet_name="חשבונית חוזה")
    
    # Map Alteco specific Hebrew columns to generic English columns
    rename_map = {
        "חודש חיוב": "billing_month",
        "ימים לחיוב": "billing_days",
        "מספר לקוח": "customer_id",
        "שם לקוח": "customer_name",
        "ח.פ לקוח": "tax_id",
        "מספר חוזה חח״י": "iec_contract",
        "מספר מונה": "meter_number",
        "מתח": "voltage",
        "בסיסי": "basic",
        "תעו״ז": "tou",
        "סוג צרכן": "consumer_type",
        "סוג חיוב": "billing_type",
        "תעריף": "tariff",
        "תשלום קבוע": "fixed_payment",
        "תאריך התחלת החוזה": "contract_start_date",
        "KVA": "kva"
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


def load_electra_data(file_path):
    """
    Loads Electra's specific multiple sheets, performs internal transformations,
    and returns a single, standardized DataFrame matching the generic schema.
    """
    # Efficiently read all sheets from the in-memory file object at once
    all_sheets = pd.read_excel(file_path, sheet_name=None)
    df_meta = all_sheets["מצבת לקוחות"]
    df_drft = all_sheets["DRFT"]

    # 1. Filter out dismantled meters immediately
    if "סטטוס מתקן" in df_meta.columns:
        df_meta = df_meta[df_meta["סטטוס מתקן"] == "פעיל"]

    # 2. Process Electra's raw transactional DRFT lines
    df_drft['derived_month'] = pd.to_datetime(df_drft['draftDate']).dt.strftime('%Y-%m')
    df_drft['derived_days'] = (pd.to_datetime(df_drft['draftLineTo']) - pd.to_datetime(df_drft['draftLineFrom'])).dt.days

    # Compress multiple billing rows to one summary row per Customer ID
    drft_summary = df_drft.groupby('AccountExtID').agg({
        'derived_month': 'first',
        'derived_days': 'first',
        'AccountName': 'first'
    }).reset_index()

    # 3. Standardize IDs before internal merge
    df_meta['מספר לקוח'] = df_meta['מספר לקוח'].astype(str).str.strip()
    drft_summary['AccountExtID'] = drft_summary['AccountExtID'].astype(str).str.strip()

    # 4. Merge Electra's internal metadata with its billing summary
    electra_unified = pd.merge(df_meta, drft_summary, left_on="מספר לקוח", right_on="AccountExtID", how="left")

    # 5. Map Electra specific columns to the generic English schema
    rename_map = {
        "derived_month": "billing_month",
        "derived_days": "billing_days",
        "מספר לקוח": "customer_id",
        "AccountName": "customer_name",
        "ת.ז./ח.פ.": "tax_id",
        'מספר חח"י': "iec_contract",
        "מספר מונה": "meter_number",
        "מתח": "voltage",
        "קבוע": "fixed_payment",
        "סוג לקוח": "consumer_type",
        "תאריך הצטרפות": "contract_start_date",
        "KVA": "kva"
    }
    electra_unified = electra_unified.rename(columns=rename_map)

    # Ensure all STANDARD_SCHEMA columns exist (fill with None if missing)
    for col in STANDARD_SCHEMA:
        if col not in electra_unified.columns:
            electra_unified[col] = None

    # Clean string identifiers
    for col in ["meter_number", "customer_id"]:
        if col in electra_unified.columns:
            electra_unified[col] = electra_unified[col].astype(str).str.strip()

    return electra_unified[STANDARD_SCHEMA]
