import os
import sys

# PATH FIX: Inject root directory path so python can seamlessly find the 'src' package
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import unittest
import pandas as pd
from src.reconciliation_engine import ReconciliationEngine


class TestReconciliationEngine(unittest.TestCase):

    def test_perfect_match_generates_zero_discrepancies(self):
        """
        [Positive Test] Verify that when Alteco and Client data
        are identical, the engine flags absolutely nothing.
        """
        df_alteco = pd.DataFrame([{
            "meter_number": "M-GOOD",
            "billing_month": "2026-05",
            "billing_days": 31,
            "customer_id": "12345",
            "customer_name": "Perfect Client Ltd",
            "tax_id": "515151",
            "iec_contract": "999888",
            "voltage": "High Voltage",
            "basic": "Yes",
            "tou": "Full",
            "consumer_type": "Commercial",
            "billing_type": "Standard",
            "tariff": "General",
            "fixed_payment": 250.0,
            "contract_start_date": "2024-01-01"
        }])
        
        # Identity match
        df_client = df_alteco.copy()

        engine = ReconciliationEngine(df_alteco, df_client)
        df_errors = engine.run_step_1_metadata()

        self.assertTrue(df_errors.empty)

    def test_catch_multiple_field_mismatches(self):
        """
        [Negative Test] Sabotage multiple fields to verify the engine
        accurately flags errors for specific mismatched categories.
        """
        df_alteco = pd.DataFrame([{
            "meter_number": "M-ERR-1",
            "billing_month": "2026-05",
            "billing_days": 31,              # Will mismatch
            "customer_id": "12345",
            "customer_name": "Company A",     # Will mismatch
            "tax_id": "515151",
            "iec_contract": "999888",
            "voltage": "High Voltage",
            "basic": "Yes",
            "tou": "Full",
            "consumer_type": "Commercial",
            "billing_type": "Standard",
            "tariff": "General",
            "fixed_payment": 250.0,
            "contract_start_date": "2024-01-01"
        }])

        df_client = pd.DataFrame([{
            "meter_number": "M-ERR-1",
            "billing_month": "2026-05",
            "billing_days": 28,              # Sabotaged
            "customer_id": "12345",
            "customer_name": "Company B",     # Sabotaged
            "tax_id": "515151",
            "iec_contract": "999888",
            "voltage": "High Voltage",
            "basic": "Yes",
            "tou": "Full",
            "consumer_type": "Commercial",
            "billing_type": "Standard",
            "tariff": "General",
            "fixed_payment": 250.0,
            "contract_start_date": "2024-01-01"
        }])

        engine = ReconciliationEngine(df_alteco, df_client)
        df_errors = engine.run_step_1_metadata()

        # We expect exactly 2 logged errors for this meter
        self.assertEqual(len(df_errors), 2)
        
        mismatched_fields = df_errors["Mismatched Field"].values
        self.assertIn("Billing Days (ימים לחיוב)", mismatched_fields)
        self.assertIn("Customer Name (שם לקוח)", mismatched_fields)

    def test_type_resilience_mixed_days_format(self):
        """
        [Edge Case Test] Test that string '31' vs integer 31 does NOT
        trigger a false positive mismatch because the engine normalizes types.
        """
        df_alteco = pd.DataFrame([{
            "meter_number": "M-TYPE",
            "billing_month": "2026-05",
            "billing_days": "31",            # Passed as a string deliberately
            "customer_id": "12345",
            "customer_name": "Client",
            "tax_id": "515151",
            "iec_contract": "999888",
            "voltage": "High",
            "basic": "Yes",
            "tou": "Full",
            "consumer_type": "Commercial",
            "billing_type": "Standard", 
            "tariff": "General",
            "fixed_payment": "250",          # String fixed payment
            "contract_start_date": "2024-01-01"
        }])

        df_client = pd.DataFrame([{
            "meter_number": "M-TYPE",
            "billing_month": "2026-05",
            "billing_days": 31,              # Passed as an integer
            "customer_id": "12345",
            "customer_name": "Client",
            "tax_id": "515151",
            "iec_contract": "999888",
            "voltage": "High",
            "basic": "Yes",
            "tou": "Full",
            "consumer_type": "Commercial",
            "billing_type": "Standard",
            "tariff": "General", 
            "fixed_payment": 250.0,          # Float fixed payment
            "contract_start_date": "2024-01-01"
        }])

        engine = ReconciliationEngine(df_alteco, df_client)
        df_errors = engine.run_step_1_metadata()

        # Should be clean since string vs int are normalized during comparison
        self.assertTrue(df_errors.empty)

    def test_date_normalization_prevents_false_positives(self):
        """
        [Edge Case Test] Verify that different valid date/datetime formats
        for the same day do not trigger a false positive.
        """
        df_alteco = pd.DataFrame([{
            "meter_number": "M-DATE",
            "billing_month": "2026-05", "billing_days": 31, "customer_id": "1",
            "customer_name": "Client", "tax_id": "1", "iec_contract": "1",
            "voltage": "High", "basic": "Yes", "tou": "Full", "consumer_type": "C",
            "billing_type": "S", "tariff": "G", "fixed_payment": 100,
            "contract_start_date": "2024-01-01"  # Date as a simple string
        }])

        df_client = pd.DataFrame([{
            "meter_number": "M-DATE",
            "billing_month": "2026-05", "billing_days": 31, "customer_id": "1",
            "customer_name": "Client", "tax_id": "1", "iec_contract": "1",
            "voltage": "High", "basic": "Yes", "tou": "Full", "consumer_type": "C",
            "billing_type": "S", "tariff": "G", "fixed_payment": 100,
            # Date as a full timestamp string, which pandas will parse
            "contract_start_date": "2024-01-01 00:00:00"
        }])

        engine = ReconciliationEngine(df_alteco, df_client)
        df_errors = engine.run_step_1_metadata()

        # The engine should normalize both to 'YYYY-MM-DD' and find no errors
        self.assertTrue(df_errors.empty, "Date normalization failed; different formats were not matched.")

    def test_missing_values_graceful_skipping(self):
        """
        [Edge Case Test] If a field is NaN/Missing on one side, ensure
        the engine handles it gracefully without crashing or false-flagging.
        """
        df_alteco = pd.DataFrame([{
            "meter_number": "M-MISSING",
            "billing_month": "2026-05",
            "billing_days": 31,
            "customer_id": "12345",
            "customer_name": "Client",
            "tax_id": None,                  # Missing value
            "iec_contract": "999888",
            "voltage": None,
            "basic": None,
            "tou": None,
            "consumer_type": None,
            "billing_type": None,
            "tariff": None,
            "fixed_payment": None,
            "contract_start_date": "2024-01-01"
        }])

        df_client = pd.DataFrame([{
            "meter_number": "M-MISSING",
            "billing_month": "2026-05",
            "billing_days": 31,
            "customer_id": "12345",
            "customer_name": "Client",
            "tax_id": "515151",              # Available here
            "iec_contract": "999888",
            "voltage": "Low",
            "basic": "No",
            "tou": "Low",
            "consumer_type": "Private",
            "billing_type": "Alt",
            "tariff": "Private Tariff",
            "fixed_payment": 100.0,
            "contract_start_date": "2024-01-01"
        }])

        engine = ReconciliationEngine(df_alteco, df_client)
        
        # Code execution validation (making sure pd.notna catches it and doesn't crash)
        try:
            df_errors = engine.run_step_1_metadata()
            # Since fields were missing on one side, it shouldn't trigger an explicit mismatch error
            self.assertTrue(df_errors.empty)
        except Exception as e:
            self.fail(f"Engine crashed on missing values with error: {e}")


# Enable high verbosity output directly inside the execution context
if __name__ == "__main__":
    unittest.main(verbosity=2)
