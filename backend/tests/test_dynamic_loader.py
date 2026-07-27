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
            "line_items": {"sheet": "Lines", "group_by_column": "AcctID"},
            "calculated_fields": {},
        }

    def test_all_meters_included_regardless_of_status(self):
        """There's no active/inactive filtering anymore — any meter present
        in the primary sheet is treated as valid."""
        df = load_mapped_data(TEMP_FILE, self._base_mapping())
        self.assertEqual(len(df), 3)
        self.assertIn("M-3", df["meter_number"].values)

    def test_equals_filter_matches_exact_type(self):
        mapping = self._base_mapping()
        mapping["calculated_fields"]["total_kwh"] = {
            "sheet": "Lines",
            "group_by_column": "AcctID",
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
            "sheet": "Lines",
            "group_by_column": "AcctID",
            "value_column": "Amount",
            "filters": [{"column": "Description", "match_type": "contains_any", "values": ["KVA"]}],
        }
        df = load_mapped_data(TEMP_FILE, mapping)
        c1 = df[df["customer_id"] == "C1"].iloc[0]
        self.assertEqual(c1["kva_fixed_charge"], 50.0)

    def test_combined_filters_are_anded_together(self):
        mapping = self._base_mapping()
        mapping["calculated_fields"]["total_kwh"] = {
            "sheet": "Lines",
            "group_by_column": "AcctID",
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
        mapping["calculated_fields"]["total_payment"] = {
            "sheet": "Lines", "group_by_column": "AcctID", "value_column": "Amount", "filters": []
        }
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

    # ---- Edge cases ----

    def test_equals_filter_is_case_sensitive(self):
        """Documents current behavior: 'equals' does an exact-case match, so a
        differently-cased source value (e.g. a client export using 'usage'
        instead of 'Usage') silently matches nothing rather than erroring."""
        mapping = self._base_mapping()
        mapping["calculated_fields"]["total_kwh"] = {
            "sheet": "Lines",
            "group_by_column": "AcctID",
            "value_column": "Qty",
            "filters": [{"column": "LineType", "match_type": "equals", "values": ["usage"]}],
        }
        df = load_mapped_data(TEMP_FILE, mapping)
        c1 = df[df["customer_id"] == "C1"].iloc[0]
        self.assertTrue(pd.isna(c1["total_kwh"]))

    def test_filter_matching_nothing_yields_nan_not_zero(self):
        """A customer with line items, but none matching the filter, gets NaN
        for that calculated field — distinct from a customer who legitimately
        has a zero total (e.g. billed only for recurring charges this month)."""
        mapping = self._base_mapping()
        mapping["calculated_fields"]["kva_fixed_charge"] = {
            "sheet": "Lines",
            "group_by_column": "AcctID",
            "value_column": "Amount",
            "filters": [{"column": "Description", "match_type": "contains_any", "values": ["NoSuchKeyword"]}],
        }
        df = load_mapped_data(TEMP_FILE, mapping)
        c1 = df[df["customer_id"] == "C1"].iloc[0]
        self.assertTrue(pd.isna(c1["kva_fixed_charge"]))

    def test_field_from_line_items_takes_first_row_per_customer(self):
        """When a field lives on the line-items sheet (one row per billing
        line), the value taken is the FIRST matching row for that customer in
        sheet order — not an aggregate. Documented so it isn't mistaken for a
        bug when a client file has multiple line-item rows per customer."""
        mapping = self._base_mapping()
        mapping["field_mappings"]["customer_name"] = {"sheet": "Lines", "column": "Description"}
        df = load_mapped_data(TEMP_FILE, mapping)
        c1 = df[df["customer_id"] == "C1"].iloc[0]
        self.assertEqual(c1["customer_name"], "Night rate")

    def test_contains_any_handles_regex_special_characters(self):
        """A filter keyword containing regex metacharacters (parens, etc.)
        must be treated as a literal substring, not a regex pattern — the
        engine re.escape()s each value before building the pattern."""
        special_file = "temp_regex_special_test.xlsx"
        df_meta = pd.DataFrame({"CustomerID": ["C1"], "MeterNo": ["M-1"]})
        df_lines = pd.DataFrame({
            "AcctID": ["C1", "C1"],
            "Description": ["Fee (KVA)", "Other charge"],
            "Amount": [42.0, 10.0],
        })
        with pd.ExcelWriter(special_file) as writer:
            df_meta.to_excel(writer, sheet_name="Meta", index=False)
            df_lines.to_excel(writer, sheet_name="Lines", index=False)
        try:
            mapping = {
                "field_mappings": {
                    "customer_id": {"sheet": "Meta", "column": "CustomerID"},
                    "meter_number": {"sheet": "Meta", "column": "MeterNo"},
                },
                "line_items": {"sheet": "Lines", "group_by_column": "AcctID"},
                "calculated_fields": {
                    "total_payment": {
                        "sheet": "Lines",
                        "group_by_column": "AcctID",
                        "value_column": "Amount",
                        "filters": [{"column": "Description", "match_type": "contains_any", "values": ["(KVA)"]}],
                    }
                },
            }
            df = load_mapped_data(special_file, mapping)
            c1 = df[df["customer_id"] == "C1"].iloc[0]
            self.assertEqual(c1["total_payment"], 42.0)
        finally:
            if os.path.exists(special_file):
                os.remove(special_file)

    def test_non_numeric_value_column_treated_as_zero(self):
        """Garbage (non-numeric) values in the value column are coerced to 0
        rather than crashing the sum — a client export with a stray text note
        in an otherwise-numeric column shouldn't break reconciliation."""
        junk_file = "temp_nonnumeric_test.xlsx"
        df_meta = pd.DataFrame({"CustomerID": ["C1"], "MeterNo": ["M-1"]})
        df_lines = pd.DataFrame({
            "AcctID": ["C1", "C1", "C1"],
            "Amount": pd.array(["100.5", "N/A", 50], dtype="object"),
        })
        with pd.ExcelWriter(junk_file) as writer:
            df_meta.to_excel(writer, sheet_name="Meta", index=False)
            df_lines.to_excel(writer, sheet_name="Lines", index=False)
        try:
            mapping = {
                "field_mappings": {
                    "customer_id": {"sheet": "Meta", "column": "CustomerID"},
                    "meter_number": {"sheet": "Meta", "column": "MeterNo"},
                },
                "line_items": {"sheet": "Lines", "group_by_column": "AcctID"},
                "calculated_fields": {
                    "total_payment": {"sheet": "Lines", "group_by_column": "AcctID", "value_column": "Amount", "filters": []}
                },
            }
            df = load_mapped_data(junk_file, mapping)
            c1 = df[df["customer_id"] == "C1"].iloc[0]
            # "N/A" coerces to 0, so 100.5 + 0 + 50 = 150.5
            self.assertEqual(c1["total_payment"], 150.5)
        finally:
            if os.path.exists(junk_file):
                os.remove(junk_file)

    def test_calculated_fields_are_fully_independent(self):
        """Two calculated fields can each point at a completely different
        sheet with a completely different group-by column — configuring one
        must have zero effect on the other, and neither depends on the
        shared field_mappings/billing_month line-items sheet."""
        multi_file = "temp_independent_calc_test.xlsx"
        df_meta = pd.DataFrame({"CustomerID": ["C1"], "MeterNo": ["M-1"]})
        df_usage = pd.DataFrame({
            "UsageAcct": ["C1", "C1"],
            "Kwh": [100.0, 50.0],
        })
        df_billing = pd.DataFrame({
            "BillingCustomerRef": ["C1"],
            "Charge": [999.0],
        })
        with pd.ExcelWriter(multi_file) as writer:
            df_meta.to_excel(writer, sheet_name="Meta", index=False)
            df_usage.to_excel(writer, sheet_name="Usage", index=False)
            df_billing.to_excel(writer, sheet_name="Billing", index=False)
        try:
            mapping = {
                "field_mappings": {
                    "customer_id": {"sheet": "Meta", "column": "CustomerID"},
                    "meter_number": {"sheet": "Meta", "column": "MeterNo"},
                },
                "calculated_fields": {
                    "total_kwh": {
                        "sheet": "Usage", "group_by_column": "UsageAcct",
                        "value_column": "Kwh", "filters": [],
                    },
                    "total_payment": {
                        "sheet": "Billing", "group_by_column": "BillingCustomerRef",
                        "value_column": "Charge", "filters": [],
                    },
                },
            }
            df = load_mapped_data(multi_file, mapping)
            c1 = df[df["customer_id"] == "C1"].iloc[0]
            self.assertEqual(c1["total_kwh"], 150.0)
            self.assertEqual(c1["total_payment"], 999.0)
        finally:
            if os.path.exists(multi_file):
                os.remove(multi_file)

    def test_meter_number_and_customer_id_strip_float_artifact(self):
        """A blank cell anywhere in an otherwise-numeric ID column forces the
        whole column to float64, so a clean ID like 50322013305 round-trips
        through Excel as 50322013305.0. Both meter_number and customer_id
        must come out as clean strings, not "...0"-suffixed ones — otherwise
        they'd never match the same customer's clean ID on the Alteco side."""
        float_file = "temp_dynamic_float_artifact_test.xlsx"
        df_meta = pd.DataFrame({
            "CustomerID": [377007686, None],  # None forces float64 dtype
            "MeterNo": [50322013305, 50322013306],
        })
        df_meta.to_excel(float_file, sheet_name="Meta", index=False)
        try:
            mapping = {
                "field_mappings": {
                    "customer_id": {"sheet": "Meta", "column": "CustomerID"},
                    "meter_number": {"sheet": "Meta", "column": "MeterNo"},
                },
                "calculated_fields": {},
            }
            df = load_mapped_data(float_file, mapping)
            self.assertEqual(df.loc[0, "customer_id"], "377007686")
            self.assertEqual(df.loc[0, "meter_number"], "50322013305")
            self.assertEqual(df.loc[1, "meter_number"], "50322013306")
        finally:
            if os.path.exists(float_file):
                os.remove(float_file)


if __name__ == "__main__":
    unittest.main(verbosity=2)
