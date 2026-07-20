import pandas as pd
import logging

def _normalize_for_comparison(value):
    if pd.isna(value):
        return ""
    return str(value).strip()

class ReconciliationEngine:
    def __init__(self, df_alteco, df_client):
        self.df_alteco = df_alteco
        self.df_client = df_client
        self.discrepancies_step1 = []
        self.discrepancies_step2 = []
        
        self.merged = pd.merge(self.df_alteco, self.df_client, on="meter_number", suffixes=('_Alteco', '_Client'))

    def run_step_1_metadata(self):
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
        
        for _, row in self.merged.iterrows():
            meter_num = row["meter_number"]
            client_name = row.get("customer_name_Alteco", "Unknown Client")
            
            for field, display_name in fields_to_check.items():
                name_en, name_he = display_name
                val_alteco = row.get(f"{field}_Alteco") 
                val_client = row.get(f"{field}_Client")
                
                if field == "billing_month" and pd.notna(val_alteco):
                    try:
                        val_alteco = pd.to_datetime(val_alteco).strftime('%Y-%m')
                    except Exception:
                        pass
                
                if field == "contract_start_date" and pd.notna(val_alteco) and pd.notna(val_client):
                    try:
                        val_alteco = pd.to_datetime(val_alteco).strftime('%Y-%m-%d')
                        val_client = pd.to_datetime(val_client).strftime('%Y-%m-%d')
                    except Exception:
                        pass
                
                norm_alteco = _normalize_for_comparison(val_alteco)
                norm_client = _normalize_for_comparison(val_client)
                
                if norm_alteco != "" and norm_client != "":
                    is_mismatch = False
                    if field in ["billing_days", "fixed_payment", "kva"]:
                        try:
                            if float(val_alteco) != float(val_client):
                                is_mismatch = True
                        except (ValueError, TypeError):
                            if norm_alteco != norm_client:
                                is_mismatch = True
                    else:
                        if norm_alteco != norm_client:
                            is_mismatch = True

                    if is_mismatch:
                        logging.warning(f"PHASE 1 MISMATCH for Meter '{meter_num}' on '{name_en}'")
                        self.discrepancies_step1.append({
                            "Meter Number": meter_num,
                            "Client Name": client_name,
                            "Mismatched Field": name_en,
                            "Original Field (Hebrew)": name_he,
                            "Alteco Value": val_alteco,
                            "Client Value": val_client
                        })

    def run_step_2_consumption(self):
        fields_to_check = {
            "total_kwh": ("Total Consumption (kWh)", "סה״כ צריכה קוט״ש"),
            "offpeak_kwh": ("Off-Peak Consumption (kWh)", "צריכה בשפל קוט״ש"),
            "peak_kwh": ("Peak Consumption (kWh)", "צריכה בפסגה קוט״ש")
        }
        
        tolerance = 0.5 
        
        for _, row in self.merged.iterrows():
            meter_num = row["meter_number"]
            client_name = row.get("customer_name_Alteco", "Unknown Client")
            
            for field, display_name in fields_to_check.items():
                name_en, name_he = display_name
                val_alteco = row.get(f"{field}_Alteco") 
                val_client = row.get(f"{field}_Client")
                
                norm_alteco = _normalize_for_comparison(val_alteco)
                norm_client = _normalize_for_comparison(val_client)
                
                if norm_alteco != "" and norm_client != "":
                    try:
                        num_alteco = float(val_alteco)
                        num_client = float(val_client)
                        
                        if abs(num_alteco - num_client) > tolerance:
                            logging.warning(f"PHASE 2 MISMATCH for Meter '{meter_num}' on '{name_en}'")
                            self.discrepancies_step2.append({
                                "Meter Number": meter_num,
                                "Client Name": client_name,
                                "Mismatched Field": name_en,
                                "Original Field (Hebrew)": name_he,
                                "Alteco Value": round(num_alteco, 2),
                                "Client Value": round(num_client, 2)
                            })
                    except (ValueError, TypeError):
                        logging.error(f"Invalid consumption data type for Meter '{meter_num}'")
                        self.discrepancies_step2.append({
                            "Meter Number": meter_num,
                            "Client Name": client_name,
                            "Mismatched Field": name_en,
                            "Original Field (Hebrew)": name_he,
                            "Alteco Value": val_alteco,
                            "Client Value": val_client
                        })

    def run_all_steps(self):
        """
        Orchestrator: Runs all phases and returns a dictionary with separate DataFrames.
        """
        self.discrepancies_step1 = []
        self.discrepancies_step2 = []
        
        self.run_step_1_metadata()
        self.run_step_2_consumption()
        
        df_step1 = pd.DataFrame(self.discrepancies_step1).replace({pd.NaT: None, pd.NA: None, float('nan'): None})
        df_step2 = pd.DataFrame(self.discrepancies_step2).replace({pd.NaT: None, pd.NA: None, float('nan'): None})
        
        return {
            "step1": df_step1,
            "step2": df_step2
        }