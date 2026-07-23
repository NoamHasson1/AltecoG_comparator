import os
import sys

# PATH FIX
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import unittest
import pandas as pd
from src.dynamic_loader import inspect_workbook, load_mapped_data

TEMP_FILE = "temp_dynamic_loader_test.xlsx"


class TestDynamicLoader(unittest.TestCase):

    def setUp(self):
        df_meta = pd.DataFrame({
            "CustomerID": ["C1", "C2", "C3"],
            "MeterNo": ["M-1", "M-2", "M-3"],
            "Status": ["Active", "Active", "Inactive"],
        })
        df_lines = pd.DataFrame({
            "AcctID": ["C1", "C1", "C1", "C2"],
            "LineType": ["Usage", "Usage", "Fixed", "Usage"],
            "Description": ["Night rate", "Day rate", "KVA charge", "Day rate"],
            "Qty": [10, 20, 5, 40],
            "Amount": [100.0, 200.0, 50.0, 400.0],
        })
        with pd.ExcelWriter(TEMP_FILE) as writer:
            df_meta.to_excel(writer, sheet_name="Meta", index=False)
            df_lines.to_excel(writer, sheet_name="Lines", index=False)

    def tearDown(self):
        if os.path.exists(TEMP_FILE):
            os.remove(TEMP_FILE)

    def test_inspect_workbook_returns_sheets_columns_and_samples(self):
        result = inspect_workbook(TEMP_FILE)
        sheet_names = [s["name"] for s in result["sheets"]]
        self.assertIn("Meta", sheet_names)
        self.assertIn("Lines", sheet_names)

        meta_sheet = next(s for s in result["sheets"] if s["name"] == "Meta")
        self.assertEqual(meta_sheet["columns"], ["CustomerID", "MeterNo", "Status"])
        self.assertEqual(len(meta_sheet["sample_rows"]), 3)
        self.assertEqual(meta_sheet["sample_rows"][0]["CustomerID"], "C1")

    def _base_mapping(self):
        return {
            "field_mappings": {
                "customer_id": {"sheet": "Meta", "column": "CustomerID"},
                "meter_number": {"sheet": "Meta", "column": "MeterNo"},
            },
            "active_filter": {"sheet": "Meta", "column": "Status", "value": "Active"},
            "line_items": {"sheet": "Lines", "group_by_column": "AcctID"},
            "calculated_fields": {},
        }

    def test_active_filter_excludes_inactive_rows(self):
        df = load_mapped_data(TEMP_FILE, self._base_mapping())
        self.assertEqual(len(df), 2)
        self.assertNotIn("M-3", df["meter_number"].values)

    def test_equals_filter_matches_exact_type(self):
        mapping = self._base_mapping()
        mapping["calculated_fields"]["total_kwh"] = {
            "value_column": "Qty",
            "filters": [{"column": "LineType", "match_type": "equals", "values": ["Usage"]}],
        }
        df = load_mapped_data(TEMP_FILE, mapping)
        c1 = df[df["customer_id"] == "C1"].iloc[0]
        # Only the two 'Usage' rows (10 + 20), not the 'Fixed' row (5)
        self.assertEqual(c1["total_kwh"], 30.0)

    def test_contains_any_filter_matches_keywords(self):
        mapping = self._base_mapping()
        mapping["calculated_fields"]["kva_fixed_charge"] = {
            "value_column": "Amount",
            "filters": [{"column": "Description", "match_type": "contains_any", "values": ["KVA"]}],
        }
        df = load_mapped_data(TEMP_FILE, mapping)
        c1 = df[df["customer_id"] == "C1"].iloc[0]
        self.assertEqual(c1["kva_fixed_charge"], 50.0)

    def test_combined_filters_are_anded_together(self):
        mapping = self._base_mapping()
        mapping["calculated_fields"]["total_kwh"] = {
            "value_column": "Qty",
            "filters": [
                {"column": "LineType", "match_type": "equals", "values": ["Usage"]},
                {"column": "Description", "match_type": "contains_any", "values": ["Night"]},
            ],
        }
        df = load_mapped_data(TEMP_FILE, mapping)
        c1 = df[df["customer_id"] == "C1"].iloc[0]
        # Only the 'Usage' + 'Night rate' row (10), not the 'Usage' + 'Day rate' row (20)
        self.assertEqual(c1["total_kwh"], 10.0)

    def test_no_filters_sums_everything(self):
        mapping = self._base_mapping()
        mapping["calculated_fields"]["total_payment"] = {"value_column": "Amount", "filters": []}
        df = load_mapped_data(TEMP_FILE, mapping)
        c1 = df[df["customer_id"] == "C1"].iloc[0]
        self.assertEqual(c1["total_payment"], 350.0)

    def test_field_from_unknown_sheet_raises(self):
        mapping = self._base_mapping()
        mapping["field_mappings"]["customer_name"] = {"sheet": "NoSuchSheet", "column": "X"}
        with self.assertRaises(ValueError):
            load_mapped_data(TEMP_FILE, mapping)

    def test_missing_required_join_keys_raises(self):
        mapping = self._base_mapping()
        del mapping["field_mappings"]["meter_number"]
        with self.assertRaises(ValueError):
            load_mapped_data(TEMP_FILE, mapping)

    def test_unmapped_optional_field_stays_none(self):
        df = load_mapped_data(TEMP_FILE, self._base_mapping())
        self.assertTrue(df["tariff"].isna().all())


if __name__ == "__main__":
    unittest.main(verbosity=2)
