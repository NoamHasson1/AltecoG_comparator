import json
import os
import sys

# PATH FIX
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import unittest
import pandas as pd
from src.data_loader import load_alteco_data
from src.dynamic_loader import load_mapped_data

TEMP_ALTECO = "temp_alteco_test.xlsx"
TEMP_ELECTRA = "temp_electra_test.xlsx"
DEFAULT_MAPPING_PATH = os.path.join(os.path.dirname(__file__), "..", "mappings", "electra_default.json")


class TestDataLoader(unittest.TestCase):

    def setUp(self):
        with open(DEFAULT_MAPPING_PATH, "r", encoding="utf-8") as f:
            self.electra_mapping = json.load(f)

        # 1. Create dummy Alteco file
        alteco_data = {
            "מספר מונה": [" M-11111 ", "M-22222"],
            "חודש חיוב": ["2026-05", "2026-05"],
            "ימים לחיוב": [31, 31],
            "מספר לקוח": ["377001", "377002"],
            "שם לקוח": ["Client A", "Client B"],
            "ח.פ לקוח": ["123", "456"],
            "מספר חוזה חח״י": ["111", "222"],
            "תאריך התחלת החוזה": ["2023-09-01", "2023-09-01"],
            "סה״כ צריכה קוט״ש": [1000, 2000]
        }
        alteco_df = pd.DataFrame(alteco_data)
        alteco_df.to_excel(TEMP_ALTECO, sheet_name="חשבונית חוזה", index=False)

        # 2. Create dummy Electra-shaped data with BOTH required sheets
        electra_meta_data = {
            "מספר מונה": ["M-11111", " M-22222 ", "M-33333"],
            "סטטוס מתקן": ["פעיל", "פעיל", "מפורק"],
            "מספר לקוח": ["377001", "377002", "377003"],
            "ת.ז/ח.פ": ["123", "456", "789"],
            "מספר חח״י": ["111", "222", "333"],
            "מתח": ["HV", "HV", "HV"],
            "קבוע": [50.0, 60.0, 70.0],
            "KVA": [27.71, 30.0, 25.0],
            "תאריך הצטרפות": ["2023-09-01", "2023-09-01", "2023-09-01"]
        }
        df_meta = pd.DataFrame(electra_meta_data)

        electra_drft_data = {
            "AccountExtID": ["377001", "377001", "377001", "377002", "377003"],
            "AccountName": ["Client A", "Client A", "Client A", "Client B", "Client C"],
            "draftDate": ["2026-05-31", "2026-05-31", "2026-05-31", "2026-05-31", "2026-05-31"],
            "draftLineFrom": ["2026-05-01", "2026-05-01", "2026-05-01", "2026-05-01", "2026-05-01"],
            "draftLineTo": ["2026-06-01", "2026-06-01", "2026-06-01", "2026-06-01", "2026-06-01"],
            "DraftLineType": ["Detail usage", "Detail usage", "Detail recurring", "Detail recurring", "Detail usage"],
            "draftLineDescription": ["לילה - צריכה", "פסגה - צריכה", "KVA - פרטיים", "תשלום קבוע", "רגיל"],
            "Quantity": [300, 700, 15, 1, 500],
            "LineTotalAmount": [900, 2100, 45, 10, 1500]
        }
        df_drft = pd.DataFrame(electra_drft_data)

        with pd.ExcelWriter(TEMP_ELECTRA) as writer:
            df_meta.to_excel(writer, sheet_name="מצבת לקוחות", index=False)
            df_drft.to_excel(writer, sheet_name="DRFT", index=False)

    def tearDown(self):
        if os.path.exists(TEMP_ALTECO):
            os.remove(TEMP_ALTECO)
        if os.path.exists(TEMP_ELECTRA):
            os.remove(TEMP_ELECTRA)

    def test_alteco_loader_strips_whitespace_and_renames(self):
        df = load_alteco_data(TEMP_ALTECO)
        self.assertEqual(df.loc[0, "meter_number"], "M-11111")
        self.assertEqual(df.loc[0, "total_kwh"], 1000)

    def test_mapped_loader_filters_dismantled_meters(self):
        df = load_mapped_data(TEMP_ELECTRA, self.electra_mapping)
        self.assertEqual(len(df), 2)
        self.assertNotIn("M-33333", df["meter_number"].values)

    def test_mapped_loader_maps_tax_id_and_iec_contract(self):
        df = load_mapped_data(TEMP_ELECTRA, self.electra_mapping)
        client_a = df[df['customer_id'] == "377001"].iloc[0]
        self.assertEqual(str(client_a['tax_id']), "123")
        self.assertEqual(str(client_a['iec_contract']), "111")

    def test_mapped_loader_calculates_consumption_correctly(self):
        """Verify Phase 2 calculation: sum Quantity for 'Detail usage' lines."""
        df = load_mapped_data(TEMP_ELECTRA, self.electra_mapping)
        # Client 377001 has two 'Detail usage' lines: 300 + 700
        client_a = df[df['customer_id'] == "377001"].iloc[0]

        self.assertEqual(client_a['total_kwh'], 1000.0)

        # Client 377002 only has 'Detail recurring', so total_kwh should be NaN/None
        client_b = df[df['customer_id'] == "377002"].iloc[0]
        self.assertTrue(pd.isna(client_b['total_kwh']))

    def test_mapped_loader_calculates_financial_charges_correctly(self):
        """Verify Phase 3 calculations: total payment and KVA fixed charge (both from LineTotalAmount)."""
        df = load_mapped_data(TEMP_ELECTRA, self.electra_mapping)
        # Client 377001 lines: 900 + 2100 + 45 = 3045 total payment; KVA line's LineTotalAmount is 45
        client_a = df[df['customer_id'] == "377001"].iloc[0]

        self.assertEqual(client_a['total_payment'], 3045.0)
        self.assertEqual(client_a['kva_fixed_charge'], 45.0)

    def test_mapped_loader_customer_name_pulled_from_line_items_sheet(self):
        """customer_name in the default mapping lives on the DRFT sheet, not the primary sheet."""
        df = load_mapped_data(TEMP_ELECTRA, self.electra_mapping)
        client_a = df[df['customer_id'] == "377001"].iloc[0]
        self.assertEqual(client_a['customer_name'], "Client A")

    def test_mapped_loader_unmapped_field_stays_none(self):
        """tou/billing_type/tariff aren't in the default mapping's field_mappings; must stay None, not crash."""
        df = load_mapped_data(TEMP_ELECTRA, self.electra_mapping)
        self.assertTrue(df['tou'].isna().all())
        self.assertTrue(df['billing_type'].isna().all())
        self.assertTrue(df['tariff'].isna().all())


if __name__ == "__main__":
    unittest.main(verbosity=2)
