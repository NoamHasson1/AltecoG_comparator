import pandas as pd

class ReconciliationEngine:
    def __init__(self, df_alteco, df_client):
        """
        Generic Engine: Expects both DataFrames to follow the standardized English schema.
        """
        self.df_alteco = df_alteco
        self.df_client = df_client
        self.discrepancies = []

    def run_step_1_metadata(self):
        """
        Executes a completely generic row-level metadata comparison.
        """
        self.discrepancies = []
        
        # Merge both standardized datasets on the unified key 'meter_number'
        merged = pd.merge(self.df_alteco, self.df_client, on="meter_number", suffixes=('_Alteco', '_Client'))
        
        # List of generic fields to check and their human-readable report names
        # Now separated into English and Hebrew for clean report columns
        fields_to_check = {
            "billing_month": ("Billing Month", "חודש חיוב"),
            "billing_days": ("Billing Days", "ימים לחיוב"),
            "customer_id": ("Customer ID", "מספר לקוח"),
            "customer_name": ("Customer Name", "שם לקוח"),
            "tax_id": ("Tax ID", "ח.פ לקוח"),
            "iec_contract": ("IEC Contract Number", "מספר חוזה חח״י"),
            "voltage": ("Voltage", "מתח"),
            "basic": ("Basic", "בסיסי"),
            "tou": ("TOU", "תעו״ז"),
            "consumer_type": ("Consumer Type", "סוג צרכן"),
            "billing_type": ("Billing Type", "סוג חיוב"),
            "tariff": ("Tariff", "תעריף"),
            "fixed_payment": ("Fixed Payment", "תשלום קבוע"),
            "contract_start_date": ("Contract Start Date", "תאריך התחלת החוזה"),
            "kva": ("KVA", "KVA")
        }
        
        for _, row in merged.iterrows():
            meter_num = row["meter_number"]
            client_name = row.get("customer_name_Alteco", "Unknown Client")
            
            for field, display_name in fields_to_check.items():
                name_en, name_he = display_name
                val_alteco = row.get(f"{field}_Alteco") 
                val_client = row.get(f"{field}_Client")
                
                # Normalize date strings to prevent format false-positives
                if field == "contract_start_date" and pd.notna(val_alteco) and pd.notna(val_client):
                    val_alteco = pd.to_datetime(val_alteco).strftime('%Y-%m-%d')
                    val_client = pd.to_datetime(val_client).strftime('%Y-%m-%d')
                
                # Run comparison if values exist
                if pd.notna(val_alteco) and pd.notna(val_client):
                    # Clean whitespaces if values are strings
                    if isinstance(val_alteco, str): val_alteco = val_alteco.strip()
                    if isinstance(val_client, str): val_client = val_client.strip()
                    
                    # Attempt to convert numeric-like fields to a consistent numeric type
                    if field in ["billing_days", "fixed_payment", "kva"]:
                        try:
                            val_alteco = float(val_alteco)
                            val_client = float(val_client)
                        except (ValueError, TypeError):
                            # If conversion fails, compare as is
                            pass
                        
                    # Flag if there is a mismatch
                    if str(val_alteco) != str(val_client):
                        self.discrepancies.append({
                            "Meter Number": meter_num,
                            "Client Name": client_name,
                            "Mismatched Field": name_en,
                            "Original Field (Hebrew)": name_he,
                            "Alteco Value": val_alteco,
                            "Client Value": val_client
                        })
                        
        return pd.DataFrame(self.discrepancies)
