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

    def test_step2_flags_consumption_present_on_only_one_side(self):
        """A meter with a real Electra-computed kWh but a blank Alteco value
        (e.g. Alteco never billed usage for that meter this month) must be
        reported, not silently skipped — this used to fall through a
        both-sides-required guard and produce nothing in Step 2 at all."""
        df_alteco = pd.DataFrame([{"meter_number": "M-BLANK-KWH", "total_kwh": None}])
        df_client = pd.DataFrame([{"meter_number": "M-BLANK-KWH", "total_kwh": 250.0}])

        engine = ReconciliationEngine(df_alteco, df_client)
        results = engine.run_all_steps()

        self.assertEqual(len(results["step2"]), 1)
        row = results["step2"].iloc[0]
        self.assertEqual(row["Mismatched Field"], "Total Consumption (kWh)")
        self.assertIsNone(row["Alteco Value"])
        self.assertEqual(row["Client Value"], 250.0)

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

    # ---- Edge cases ----

    def test_duplicate_meter_number_produces_cross_paired_rows(self):
        """KNOWN LIMITATION: the merge in __init__ joins purely on meter_number.
        If the same meter number appears more than once on each side (e.g. a
        physical meter reassigned to a new customer mid-year — seen in real
        client data), pandas' merge produces every combination, not just the
        intended pairing. Two of the four resulting rows here pair the wrong
        customer together and falsely mismatch on Customer ID."""
        df_alteco = pd.DataFrame([
            {"meter_number": "M-DUP", "customer_id": "C-A", "customer_name": "Alpha"},
            {"meter_number": "M-DUP", "customer_id": "C-B", "customer_name": "Beta"},
        ])
        df_client = pd.DataFrame([
            {"meter_number": "M-DUP", "customer_id": "C-A", "customer_name": "Alpha"},
            {"meter_number": "M-DUP", "customer_id": "C-B", "customer_name": "Beta"},
        ])

        engine = ReconciliationEngine(df_alteco, df_client)
        self.assertEqual(len(engine.matched), 4)  # 2x2 cross product, not 2

        results = engine.run_all_steps()
        customer_id_mismatches = results["step1"][results["step1"]["Mismatched Field"] == "Customer ID"]
        # The (A,B) and (B,A) cross-pairs mismatch; (A,A) and (B,B) correctly don't.
        self.assertEqual(len(customer_id_mismatches), 2)

        # The duplicate itself is logged (see _detect_duplicate_meters), but
        # deliberately kept out of the Meter Coverage table — it's a
        # data-quality issue, not a "missing from one side" coverage gap, and
        # the meter isn't missing from either side here.
        self.assertTrue(results["step0"].empty)

    def test_duplicate_meter_on_one_side_does_not_add_a_coverage_row(self):
        """A meter duplicated on just one side (not both) is still logged as
        a duplicate, but that fact alone must not add a row to Meter Coverage
        (step0) — only a genuine "missing from one side" gap should. Here
        the meter itself is present on both sides; the only legitimate
        coverage row is the customer (C-Y) that Electra never billed."""
        df_alteco = pd.DataFrame([
            {"meter_number": "M-SOLO-DUP", "customer_id": "C-X", "customer_name": "X Corp"},
            {"meter_number": "M-SOLO-DUP", "customer_id": "C-Y", "customer_name": "Y Corp"},
        ])
        df_client = pd.DataFrame([
            {"meter_number": "M-SOLO-DUP", "customer_id": "C-X", "customer_name": "X Corp"},
        ])

        engine = ReconciliationEngine(df_alteco, df_client)
        results = engine.run_all_steps()
        df_step0 = results["step0"]

        self.assertFalse(df_step0["Issue"].str.contains("Duplicate meter number").any())
        self.assertEqual(len(df_step0), 1)
        self.assertEqual(df_step0.iloc[0]["Match Key"], "Customer ID")
        self.assertEqual(df_step0.iloc[0]["Value"], "C-Y")

    def test_no_duplicate_meter_flagged_when_all_unique(self):
        df_alteco = pd.DataFrame([{"meter_number": "M-UNIQUE-1", "customer_id": "C-1"}])
        df_client = pd.DataFrame([{"meter_number": "M-UNIQUE-1", "customer_id": "C-1"}])

        engine = ReconciliationEngine(df_alteco, df_client)
        results = engine.run_all_steps()

        self.assertTrue(results["step0"].empty)

    def test_billing_month_client_side_not_reformatted_if_raw(self):
        """Only the Alteco-side billing_month is reformatted to 'YYYY-MM' here
        — the client side is expected to already arrive normalized (the
        dynamic mapping's derive_from_date mode does this upstream). A raw,
        unnormalized client value is NOT reformatted by the engine and shows
        as a false mismatch even for the same month — reinforcing that the
        mapping layer, not this engine, is responsible for normalizing it."""
        df_alteco = pd.DataFrame([{"meter_number": "M-BM", "billing_month": "2026-06"}])
        df_client = pd.DataFrame([{"meter_number": "M-BM", "billing_month": pd.Timestamp("2026-06-30")}])

        engine = ReconciliationEngine(df_alteco, df_client)
        results = engine.run_all_steps()
        df_step1 = results["step1"]

        self.assertEqual(len(df_step1), 1)
        self.assertEqual(df_step1.iloc[0]["Mismatched Field"], "Billing Month")

    def test_empty_dataframes_do_not_crash(self):
        df_alteco = pd.DataFrame(columns=["meter_number", "customer_id"])
        df_client = pd.DataFrame(columns=["meter_number", "customer_id"])

        engine = ReconciliationEngine(df_alteco, df_client)
        results = engine.run_all_steps()

        for key in ["step0", "step1", "step2", "step3"]:
            self.assertTrue(results[key].empty, f"{key} should be empty for empty input")


if __name__ == "__main__":
    unittest.main(verbosity=2)