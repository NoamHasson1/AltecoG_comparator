import pandas as pd
import logging

logger = logging.getLogger(__name__)

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

        logger.info(
            "RECONCILE INIT: Alteco DataFrame has %d rows, %d columns: %s",
            len(df_alteco), len(df_alteco.columns), list(df_alteco.columns),
        )
        logger.debug("RECONCILE INIT: Alteco DataFrame:\n%s", df_alteco.to_string())
        logger.info(
            "RECONCILE INIT: Electra/client DataFrame has %d rows, %d columns: %s",
            len(df_client), len(df_client.columns), list(df_client.columns),
        )
        logger.debug("RECONCILE INIT: Electra/client DataFrame:\n%s", df_client.to_string())

        self.merged = pd.merge(
            self.df_alteco, self.df_client, on="meter_number",
            suffixes=('_Alteco', '_Client'), how="outer", indicator=True
        )
        # Step 1 & 2 only make sense for meters present on both sides.
        self.matched = self.merged[self.merged["_merge"] == "both"]
        logger.info(
            "RECONCILE INIT: meter_number merge -> %d matched, %d Alteco-only, %d Electra-only",
            len(self.matched),
            len(self.merged[self.merged["_merge"] == "left_only"]),
            len(self.merged[self.merged["_merge"] == "right_only"]),
        )

    def _add_coverage_gap(self, match_key, value, client_name, issue):
        logger.warning(f"COVERAGE GAP: {match_key} '{value}' — {issue}")
        self.discrepancies_step0.append({
            "Match Key": match_key,
            "Value": value,
            "Client Name": client_name,
            "Issue": issue
        })

    def _detect_duplicate_meters(self, df, side_label):
        """
        Logs a meter number that appears more than once on one side — e.g. a
        physical meter reused/reassigned to a different customer — so the
        root cause of any resulting cross-paired Step 1/2 noise is visible in
        the terminal. This is a data-quality issue, not a coverage gap (the
        meter isn't missing from either side), so it's deliberately kept out
        of the Meter Coverage table itself, which only shows meters/customers
        present in one file and not the other.
        """
        if "meter_number" not in df.columns:
            return
        counts = df["meter_number"].value_counts()
        for meter, count in counts[counts > 1].items():
            rows = df[df["meter_number"] == meter]
            customer_ids = rows["customer_id"].dropna().astype(str).unique().tolist() if "customer_id" in df.columns else []
            names = ", ".join(customer_ids) if customer_ids else None
            logger.warning(f"DUPLICATE METER: '{meter}' appears {count} times in {side_label} (customers: {names})")

    def run_step_0_coverage(self):
        """
        Meters or customers present in only one of the two files are a coverage gap:
        either Alteco is billing something Electra has no record of, or
        Electra has an active meter/customer Alteco never billed.
        """
        logger.info("STEP 0: starting coverage check")

        # --- Duplicate meter numbers within a single side ---
        self._detect_duplicate_meters(self.df_alteco, "Alteco")
        self._detect_duplicate_meters(self.df_client, "Electra")

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
            logger.debug(
                "STEP 0: customer-level coverage — %d distinct Alteco customer_id(s), %d distinct Electra customer_id(s)",
                len(alteco_customers), len(client_customers),
            )

            merged_customers = pd.merge(
                alteco_customers, client_customers, on="customer_id",
                suffixes=("_Alteco", "_Client"), how="outer", indicator=True
            )

            for _, row in merged_customers[merged_customers["_merge"] == "left_only"].iterrows():
                self._add_coverage_gap("Customer ID", row["customer_id"], row.get("customer_name_Alteco"), "Missing from Electra")

            for _, row in merged_customers[merged_customers["_merge"] == "right_only"].iterrows():
                self._add_coverage_gap("Customer ID", row["customer_id"], row.get("customer_name_Client"), "Missing from Alteco")

        logger.info("STEP 0: finished — %d coverage issues found", len(self.discrepancies_step0))

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
        logger.info("STEP 1: starting metadata check on %d matched meter(s)", len(self.matched))

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
                    logger.debug("STEP 1: Meter '%s' field '%s' — both sides blank, skipped", meter_num, name_en)
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

                logger.debug(
                    "STEP 1: Meter '%s' field '%s' — Alteco=%r Client=%r -> %s",
                    meter_num, name_en, val_alteco, val_client, "MISMATCH" if is_mismatch else "match",
                )

                if is_mismatch:
                    logger.warning(f"PHASE 1 MISMATCH for Meter '{meter_num}' on '{name_en}'")
                    self.discrepancies_step1.append({
                        "Meter Number": meter_num,
                        "Client Name": client_name,
                        "Mismatched Field": name_en,
                        "Original Field (Hebrew)": name_he,
                        "Alteco Value": val_alteco,
                        "Client Value": val_client
                    })

        logger.info("STEP 1: finished — %d mismatches found", len(self.discrepancies_step1))

    def run_step_2_consumption(self):
        fields_to_check = {
            "total_kwh": ("Total Consumption (kWh)", "סה״כ צריכה קוט״ש")
        }

        tolerance = 0.5
        logger.info("STEP 2: starting consumption check on %d matched meter(s)", len(self.matched))

        for _, row in self.matched.iterrows():
            meter_num = row["meter_number"]
            client_name = row.get("customer_name_Alteco", "Unknown Client")

            for field, display_name in fields_to_check.items():
                name_en, name_he = display_name
                val_alteco = row.get(f"{field}_Alteco")
                val_client = row.get(f"{field}_Client")

                norm_alteco = _normalize_for_comparison(val_alteco)
                norm_client = _normalize_for_comparison(val_client)

                if norm_alteco == "" and norm_client == "":
                    logger.debug("STEP 2: Meter '%s' field '%s' — both sides blank, skipped", meter_num, name_en)
                    continue  # neither side has this field for this meter — nothing to compare

                is_mismatch = False
                out_alteco, out_client = val_alteco, val_client

                if norm_alteco == "" or norm_client == "":
                    # Field present on one side only — a real gap (e.g. Alteco
                    # never billed consumption for this meter this month) —
                    # this used to be silently skipped instead of reported.
                    is_mismatch = True
                else:
                    try:
                        num_alteco = float(val_alteco)
                        num_client = float(val_client)
                        out_alteco, out_client = round(num_alteco, 2), round(num_client, 2)
                        if abs(num_alteco - num_client) > tolerance:
                            is_mismatch = True
                    except (ValueError, TypeError):
                        logger.error(f"Invalid consumption data type for Meter '{meter_num}'")
                        is_mismatch = True

                logger.debug(
                    "STEP 2: Meter '%s' field '%s' — Alteco=%r Client=%r -> %s",
                    meter_num, name_en, out_alteco, out_client, "MISMATCH" if is_mismatch else "match",
                )

                if is_mismatch:
                    logger.warning(f"PHASE 2 MISMATCH for Meter '{meter_num}' on '{name_en}'")
                    self.discrepancies_step2.append({
                        "Meter Number": meter_num,
                        "Client Name": client_name,
                        "Mismatched Field": name_en,
                        "Original Field (Hebrew)": name_he,
                        "Alteco Value": out_alteco,
                        "Client Value": out_client
                    })

        logger.info("STEP 2: finished — %d mismatches found", len(self.discrepancies_step2))

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
            "supply_fixed_charge": ("Supply Fixed Charge", "חיוב קבוע אספקה ₪"),
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
        logger.info(
            "STEP 3: starting financial check — %d Alteco customer(s), %d Electra customer(s), %d matched by customer_id",
            len(alteco_by_customer), len(client_by_customer), len(merged_financials),
        )

        for _, row in merged_financials.iterrows():
            customer_id = row["customer_id"]
            client_name = row.get("customer_name_Alteco", "Unknown Client")

            for field, display_name in fields_to_check.items():
                name_en, name_he = display_name
                num_alteco = row.get(f"{field}_Alteco", 0.0)
                num_client = row.get(f"{field}_Client", 0.0)
                is_mismatch = abs(num_alteco - num_client) > tolerance

                logger.debug(
                    "STEP 3: Customer '%s' field '%s' — Alteco=%.2f Client=%.2f -> %s",
                    customer_id, name_en, num_alteco, num_client, "MISMATCH" if is_mismatch else "match",
                )

                if is_mismatch:
                    logger.warning(f"PHASE 3 MISMATCH for Customer '{customer_id}' on '{name_en}'")
                    self.discrepancies_step3.append({
                        "Customer ID": customer_id,
                        "Client Name": client_name,
                        "Mismatched Field": name_en,
                        "Original Field (Hebrew)": name_he,
                        "Alteco Value": round(num_alteco, 2),
                        "Client Value": round(num_client, 2)
                    })

        logger.info("STEP 3: finished — %d mismatches found", len(self.discrepancies_step3))

    def run_all_steps(self):
        """
        Orchestrator: Runs all phases and returns a dictionary with separate DataFrames.
        """
        self.discrepancies_step0 = []
        self.discrepancies_step1 = []
        self.discrepancies_step2 = []
        self.discrepancies_step3 = []

        logger.info("RECONCILE: running all steps")
        self.run_step_0_coverage()
        self.run_step_1_metadata()
        self.run_step_2_consumption()
        self.run_step_3_financials()
        logger.info(
            "RECONCILE: complete — step0=%d step1=%d step2=%d step3=%d",
            len(self.discrepancies_step0), len(self.discrepancies_step1),
            len(self.discrepancies_step2), len(self.discrepancies_step3),
        )

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
