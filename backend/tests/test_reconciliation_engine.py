import os
import sys

# PATH FIX
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import unittest
import pandas as pd
from src.reconciliation_engine import ReconciliationEngine


class TestReconciliationEngine(unittest.TestCase):

    def test_perfect_match_generates_zero_discrepancies(self):
        df_alteco = pd.DataFrame([{
            "meter_number": "M-GOOD", "billing_month": "2026-05", "billing_days": 31,
            "customer_id": "12345", "customer_name": "Perfect Client Ltd", "tax_id": "515151",
            "iec_contract": "999888", "contract_start_date": "2024-01-01",
            "total_kwh": 1000.0
        }])
        
        df_client = df_alteco.copy()
        engine = ReconciliationEngine(df_alteco, df_client)
        results = engine.run_all_steps()

        self.assertTrue(results["step0"].empty)
        self.assertTrue(results["step1"].empty)
        self.assertTrue(results["step2"].empty)
        self.assertTrue(results["step3"].empty)

    def test_catch_multiple_field_mismatches_phase1(self):
        df_alteco = pd.DataFrame([{
            "meter_number": "M-ERR-1", "billing_month": "2026-05", "billing_days": 31,
            "customer_name": "Company A"
        }])

        df_client = pd.DataFrame([{
            "meter_number": "M-ERR-1", "billing_month": "2026-05", "billing_days": 28,
            "customer_name": "Company B"
        }])

        engine = ReconciliationEngine(df_alteco, df_client)
        results = engine.run_all_steps()
        df_errors = results["step1"]

        self.assertEqual(len(df_errors), 2)
        mismatched_fields = df_errors["Mismatched Field"].values
        self.assertIn("Billing Days", mismatched_fields)
        self.assertIn("Customer Name", mismatched_fields)

    def test_type_resilience_mixed_days_format(self):
        df_alteco = pd.DataFrame([{"meter_number": "M-TYPE", "billing_days": "31"}])
        df_client = pd.DataFrame([{"meter_number": "M-TYPE", "billing_days": 31}])

        engine = ReconciliationEngine(df_alteco, df_client)
        results = engine.run_all_steps()
        
        self.assertTrue(results["step1"].empty)

    def test_field_present_on_only_one_side_is_flagged(self):
        """A field populated on one side but blank on the other is now a reportable gap, not a silent skip."""
        df_alteco = pd.DataFrame([{"meter_number": "M-MISSING", "tax_id": None}])
        df_client = pd.DataFrame([{"meter_number": "M-MISSING", "tax_id": "515151"}])

        engine = ReconciliationEngine(df_alteco, df_client)
        results = engine.run_all_steps()
        df_step1 = results["step1"]

        self.assertEqual(len(df_step1), 1)
        row = df_step1.iloc[0]
        self.assertEqual(row["Mismatched Field"], "Tax ID")
        self.assertIsNone(row["Alteco Value"])
        self.assertEqual(row["Client Value"], "515151")

    def test_field_missing_on_both_sides_is_skipped(self):
        df_alteco = pd.DataFrame([{"meter_number": "M-BOTH-MISSING", "tax_id": None}])
        df_client = pd.DataFrame([{"meter_number": "M-BOTH-MISSING", "tax_id": None}])

        engine = ReconciliationEngine(df_alteco, df_client)

        try:
            results = engine.run_all_steps()
            self.assertTrue(results["step1"].empty)
        except Exception as e:
            self.fail(f"Engine crashed on missing values with error: {e}")

    def test_step2_consumption_perfect_match_with_tolerance(self):
        """Verify that a small diff (<= 0.5) is ignored by the tolerance check."""
        df_alteco = pd.DataFrame([{"meter_number": "M-TOLERANCE", "total_kwh": 1000.0}])
        # 1000.4 is within the 0.5 tolerance limit
        df_client = pd.DataFrame([{"meter_number": "M-TOLERANCE", "total_kwh": 1000.4}])

        engine = ReconciliationEngine(df_alteco, df_client)
        results = engine.run_all_steps()
        
        self.assertTrue(results["step2"].empty, "Tolerance check failed, false positive raised!")

    def test_step2_consumption_mismatch_exceeds_tolerance(self):
        """Verify that a larger diff (> 0.5) is correctly flagged."""
        df_alteco = pd.DataFrame([{"meter_number": "M-DIFF", "total_kwh": 1000.0}])
        # 1001.0 is outside the 0.5 tolerance limit
        df_client = pd.DataFrame([{"meter_number": "M-DIFF", "total_kwh": 1001.0}])

        engine = ReconciliationEngine(df_alteco, df_client)
        results = engine.run_all_steps()
        
        self.assertEqual(len(results["step2"]), 1)
        self.assertIn("Total Consumption (kWh)", results["step2"]["Mismatched Field"].values)

    def test_step0_flags_meter_missing_from_electra(self):
        """A meter Alteco bills that Electra has no record of should surface as a coverage gap."""
        df_alteco = pd.DataFrame([{"meter_number": "M-ORPHAN", "customer_name": "Ghost Client"}])
        df_client = pd.DataFrame([{"meter_number": "M-OTHER", "customer_name": "Other Client"}])

        engine = ReconciliationEngine(df_alteco, df_client)
        results = engine.run_all_steps()
        df_step0 = results["step0"]

        self.assertEqual(len(df_step0), 2)
        orphan_row = df_step0[df_step0["Value"] == "M-ORPHAN"].iloc[0]
        self.assertEqual(orphan_row["Match Key"], "Meter Number")
        self.assertEqual(orphan_row["Issue"], "Missing from Electra")

        other_row = df_step0[df_step0["Value"] == "M-OTHER"].iloc[0]
        self.assertEqual(other_row["Match Key"], "Meter Number")
        self.assertEqual(other_row["Issue"], "Missing from Alteco")

        # Meters missing from one side shouldn't be checked in Step 1/2 at all.
        self.assertTrue(results["step1"].empty)
        self.assertTrue(results["step2"].empty)

    def test_step0_empty_when_all_meters_match(self):
        df_alteco = pd.DataFrame([{"meter_number": "M-MATCH", "customer_name": "Same Client"}])
        df_client = pd.DataFrame([{"meter_number": "M-MATCH", "customer_name": "Same Client"}])

        engine = ReconciliationEngine(df_alteco, df_client)
        results = engine.run_all_steps()

        self.assertTrue(results["step0"].empty)

    def test_step0_flags_customer_missing_even_when_meter_numbers_differ(self):
        """A customer present in only one file is a coverage gap independent of meter_number."""
        df_alteco = pd.DataFrame([
            {"meter_number": "M-A1", "customer_id": "C-1", "customer_name": "Client One"},
            {"meter_number": "M-A2", "customer_id": "C-GHOST", "customer_name": "Ghost Customer"}
        ])
        df_client = pd.DataFrame([
            {"meter_number": "M-A1", "customer_id": "C-1", "customer_name": "Client One"}
        ])

        engine = ReconciliationEngine(df_alteco, df_client)
        results = engine.run_all_steps()
        df_step0 = results["step0"]

        customer_gaps = df_step0[df_step0["Match Key"] == "Customer ID"]
        self.assertEqual(len(customer_gaps), 1)
        self.assertEqual(customer_gaps.iloc[0]["Value"], "C-GHOST")
        self.assertEqual(customer_gaps.iloc[0]["Issue"], "Missing from Electra")

    def test_step3_flags_kva_and_total_payment_mismatch(self):
        df_alteco = pd.DataFrame([{
            "meter_number": "M-FIN", "customer_id": "C-FIN", "customer_name": "Finance Client",
            "total_payment": 100.0, "kva_fixed_charge": 20.0,
            "supply_fixed_charge": 5.0, "distribution_fixed_charge": 5.0
        }])
        df_client = pd.DataFrame([{
            "meter_number": "M-FIN", "customer_id": "C-FIN", "customer_name": "Finance Client",
            "total_payment": 130.0, "kva_fixed_charge": 25.0,
            "supply_fixed_charge": 5.0, "distribution_fixed_charge": 5.0
        }])

        engine = ReconciliationEngine(df_alteco, df_client)
        results = engine.run_all_steps()
        df_step3 = results["step3"]

        self.assertEqual(len(df_step3), 2)
        mismatched_fields = set(df_step3["Mismatched Field"].values)
        self.assertEqual(mismatched_fields, {"Total Payment (Incl. VAT)", "KVA Fixed Charge"})

    def test_step3_sums_multiple_alteco_meters_per_customer(self):
        """A customer billed across two Alteco meters should have those meters summed before comparing to Electra's customer-level total."""
        df_alteco = pd.DataFrame([
            {"meter_number": "M-MULTI-1", "customer_id": "C-MULTI", "customer_name": "Multi Meter Client", "total_payment": 60.0},
            {"meter_number": "M-MULTI-2", "customer_id": "C-MULTI", "customer_name": "Multi Meter Client", "total_payment": 40.0}
        ])
        df_client = pd.DataFrame([{
            "meter_number": "M-MULTI-1", "customer_id": "C-MULTI", "customer_name": "Multi Meter Client", "total_payment": 100.0
        }])

        engine = ReconciliationEngine(df_alteco, df_client)
        results = engine.run_all_steps()

        # 60 + 40 = 100, matches Electra's single customer-level total exactly.
        self.assertTrue(results["step3"].empty)

    def test_step3_empty_when_no_financial_data_present(self):
        df_alteco = pd.DataFrame([{"meter_number": "M-NOFIN", "customer_id": "C-NOFIN"}])
        df_client = pd.DataFrame([{"meter_number": "M-NOFIN", "customer_id": "C-NOFIN"}])

        engine = ReconciliationEngine(df_alteco, df_client)
        results = engine.run_all_steps()

        self.assertTrue(results["step3"].empty)


if __name__ == "__main__":
    unittest.main(verbosity=2)