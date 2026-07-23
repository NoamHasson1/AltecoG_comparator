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
        self.discrepancies_step0 = []
        self.discrepancies_step1 = []
        self.discrepancies_step2 = []
        self.discrepancies_step3 = []

        self.merged = pd.merge(
            self.df_alteco, self.df_client, on="meter_number",
            suffixes=('_Alteco', '_Client'), how="outer", indicator=True
        )
        # Step 1 & 2 only make sense for meters present on both sides.
        self.matched = self.merged[self.merged["_merge"] == "both"]

    def _add_coverage_gap(self, match_key, value, client_name, issue):
        logging.warning(f"COVERAGE GAP: {match_key} '{value}' — {issue}")
        self.discrepancies_step0.append({
            "Match Key": match_key,
            "Value": value,
            "Client Name": client_name,
            "Issue": issue
        })

    def run_step_0_coverage(self):
        """
        Meters or customers present in only one of the two files are a coverage gap:
        either Alteco is billing something Electra has no record of, or
        Electra has an active meter/customer Alteco never billed.
        """
        # --- Meter-level coverage ---
        alteco_only_meters = self.merged[self.merged["_merge"] == "left_only"]
        client_only_meters = self.merged[self.merged["_merge"] == "right_only"]

        for _, row in alteco_only_meters.iterrows():
            self._add_coverage_gap("Meter Number", row["meter_number"], row.get("customer_name_Alteco"), "Missing from Electra")

        for _, row in client_only_meters.iterrows():
            self._add_coverage_gap("Meter Number", row["meter_number"], row.get("customer_name_Client"), "Missing from Alteco")

        # --- Customer-level coverage (a customer can exist without meter_number lining up) ---
        if "customer_id" in self.df_alteco.columns and "customer_id" in self.df_client.columns:
            def _customer_slice(df):
                df = df.copy()
                if "customer_name" not in df.columns:
                    df["customer_name"] = None
                return df[["customer_id", "customer_name"]].dropna(subset=["customer_id"]).drop_duplicates(subset=["customer_id"])

            alteco_customers = _customer_slice(self.df_alteco)
            client_customers = _customer_slice(self.df_client)

            merged_customers = pd.merge(
                alteco_customers, client_customers, on="customer_id",
                suffixes=("_Alteco", "_Client"), how="outer", indicator=True
            )

            for _, row in merged_customers[merged_customers["_merge"] == "left_only"].iterrows():
                self._add_coverage_gap("Customer ID", row["customer_id"], row.get("customer_name_Alteco"), "Missing from Electra")

            for _, row in merged_customers[merged_customers["_merge"] == "right_only"].iterrows():
                self._add_coverage_gap("Customer ID", row["customer_id"], row.get("customer_name_Client"), "Missing from Alteco")

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

        for _, row in self.matched.iterrows():
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

                if norm_alteco == "" and norm_client == "":
                    continue  # neither side has this field for this meter — nothing to compare

                is_mismatch = False
                if norm_alteco == "" or norm_client == "":
                    # Field exists on one side but not the other — a field-level coverage gap
                    is_mismatch = True
                elif field in ["billing_days", "fixed_payment", "kva"]:
                    try:
                        if float(val_alteco) != float(val_client):
                            is_mismatch = True
                    except (ValueError, TypeError):
                        if norm_alteco != norm_client:
                            is_mismatch = True
                elif field == "customer_name":
                    if sorted(norm_alteco.split()) != sorted(norm_client.split()):
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

        for _, row in self.matched.iterrows():
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

    @staticmethod
    def _with_financial_columns(df):
        """
        Guarantees customer_id/customer_name and the four Step 3 financial
        columns exist and are numeric, regardless of what the caller provided.
        """
        df = df.copy()
        for col in ["customer_id", "customer_name"]:
            if col not in df.columns:
                df[col] = None
        for col in ["total_payment", "kva_fixed_charge", "supply_fixed_charge", "distribution_fixed_charge"]:
            if col not in df.columns:
                df[col] = 0.0
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        return df

    def run_step_3_financials(self):
        """
        Compares customer-level financial totals: the overall invoice payment,
        plus the KVA / Supply / Distribution fixed charges. Electra's DRFT is
        naturally per-customer (summed there at load time); Alteco is per-meter,
        so a customer with multiple meters needs those meters summed here before
        the two sides can be compared fairly.
        """
        fields_to_check = {
            "total_payment": ("Total Payment (Incl. VAT)", "סה״כ לתשלום (כולל מע״מ) ₪"),
            "kva_fixed_charge": ("KVA Fixed Charge", "חיוב קבוע KVA ₪"),
            "supply_fixed_charge": ("Supply Fixed Charge", "חיוב קבוע אספקה  ₪"),
            "distribution_fixed_charge": ("Distribution Fixed Charge", "חיוב קבוע חלוקה ₪")
        }
        tolerance = 0.5
        financial_fields = list(fields_to_check.keys())

        df_alteco = self._with_financial_columns(self.df_alteco)
        df_client = self._with_financial_columns(self.df_client)

        agg_map = {"customer_name": "first"}
        agg_map.update({f: "sum" for f in financial_fields})

        alteco_by_customer = df_alteco.dropna(subset=["customer_id"]).groupby("customer_id", as_index=False).agg(agg_map)
        client_by_customer = df_client.dropna(subset=["customer_id"]).groupby("customer_id", as_index=False).agg(agg_map)

        merged_financials = pd.merge(
            alteco_by_customer, client_by_customer, on="customer_id",
            suffixes=("_Alteco", "_Client"), how="inner"
        )

        for _, row in merged_financials.iterrows():
            customer_id = row["customer_id"]
            client_name = row.get("customer_name_Alteco", "Unknown Client")

            for field, display_name in fields_to_check.items():
                name_en, name_he = display_name
                num_alteco = row.get(f"{field}_Alteco", 0.0)
                num_client = row.get(f"{field}_Client", 0.0)

                if abs(num_alteco - num_client) > tolerance:
                    logging.warning(f"PHASE 3 MISMATCH for Customer '{customer_id}' on '{name_en}'")
                    self.discrepancies_step3.append({
                        "Customer ID": customer_id,
                        "Client Name": client_name,
                        "Mismatched Field": name_en,
                        "Original Field (Hebrew)": name_he,
                        "Alteco Value": round(num_alteco, 2),
                        "Client Value": round(num_client, 2)
                    })

    def run_all_steps(self):
        """
        Orchestrator: Runs all phases and returns a dictionary with separate DataFrames.
        """
        self.discrepancies_step0 = []
        self.discrepancies_step1 = []
        self.discrepancies_step2 = []
        self.discrepancies_step3 = []

        self.run_step_0_coverage()
        self.run_step_1_metadata()
        self.run_step_2_consumption()
        self.run_step_3_financials()

        df_step0 = pd.DataFrame(self.discrepancies_step0).replace({pd.NaT: None, pd.NA: None, float('nan'): None})
        df_step1 = pd.DataFrame(self.discrepancies_step1).replace({pd.NaT: None, pd.NA: None, float('nan'): None})
        df_step2 = pd.DataFrame(self.discrepancies_step2).replace({pd.NaT: None, pd.NA: None, float('nan'): None})
        df_step3 = pd.DataFrame(self.discrepancies_step3).replace({pd.NaT: None, pd.NA: None, float('nan'): None})

        return {
            "step0": df_step0,
            "step1": df_step1,
            "step2": df_step2,
            "step3": df_step3
        }
