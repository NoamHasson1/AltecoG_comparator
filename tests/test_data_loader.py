import os
import sys

# PATH FIX: Tell Python to look for modules in the root directory (one level up)
# This allows us to run this script directly from anywhere without import errors.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import unittest
import pandas as pd
from src.data_loader import load_alteco_data, load_electra_data

TEMP_ALTECO = "temp_alteco_test.xlsx"
TEMP_ELECTRA = "temp_electra_test.xlsx"


class TestDataLoader(unittest.TestCase):

    def setUp(self):
        """Runs BEFORE every single test. Creates temporary test files."""
        # 1. Create dummy Alteco file (with whitespace in the meter number)
        # We include the minimal Hebrew columns that the loader maps to English
        alteco_data = {
            "מספר מונה": [" M-11111 ", "M-22222"],
            "חודש חיוב": ["2026-05", "2026-05"],
            "ימים לחיוב": [31, 31],
            "מספר לקוח": ["377001", "377002"],
            "שם לקוח": ["Client A", "Client B"],
            "ח.פ לקוח": ["123", "456"],
            "מספר חוזה חח״י": ["111", "222"],
            "תאריך התחלת החוזה": ["2023-09-01", "2023-09-01"]
        }
        alteco_df = pd.DataFrame(alteco_data)
        alteco_df.to_excel(TEMP_ALTECO, sheet_name="חשבונית חוזה", index=False)

        # 2. Create dummy Electra data with BOTH required sheets
        # Sheet 1: 'מצבת לקוחות' (Metadata & Statuses)
        electra_meta_data = {
            "מספר מונה": ["M-11111", " M-22222 ", "M-33333"],
            "סטטוס מתקן": ["פעיל", "פעיל", "מפורק"],
            "מספר לקוח": ["377001", "377002", "377003"],
            "ת.ז./ח.פ.": ["123", "456", "789"],
            "מספר חח״י": ["111", "222", "333"],
            "תאריך הצטרפות": ["2023-09-01", "2023-09-01", "2023-09-01"]
        }
        df_meta = pd.DataFrame(electra_meta_data)

        # Sheet 2: 'DRFT' (Billing & Dates)
        electra_drft_data = {
            "AccountExtID": ["377001", "377002", "377003"],
            "AccountName": ["Client A", "Client B", "Client C"],
            "draftDate": ["2026-05-31", "2026-05-31", "2026-05-31"],
            "draftLineFrom": ["2026-05-01", "2026-05-01", "2026-05-01"],
            "draftLineTo": ["2026-06-01", "2026-06-01", "2026-06-01"]
        }
        df_drft = pd.DataFrame(electra_drft_data)

        # Write both dataframes into a single Excel file with multiple sheets
        with pd.ExcelWriter(TEMP_ELECTRA) as writer:
            df_meta.to_excel(writer, sheet_name="מצבת לקוחות", index=False)
            df_drft.to_excel(writer, sheet_name="DRFT", index=False)

    def tearDown(self):
        """Runs AFTER every single test. Cleans up temporary files."""
        if os.path.exists(TEMP_ALTECO):
            os.remove(TEMP_ALTECO)
        if os.path.exists(TEMP_ELECTRA):
            os.remove(TEMP_ELECTRA)

    def test_alteco_loader_strips_whitespace_and_renames(self):
        """Verify that load_alteco_data strips spaces and converts to generic English columns."""
        df = load_alteco_data(TEMP_ALTECO)
        # Check if the column was successfully renamed and whitespace stripped
        self.assertEqual(df.loc[0, "meter_number"], "M-11111")

    def test_electra_loader_filters_dismantled_meters(self):
        """Verify that load_electra_data filters out inactive ('מפורק') meters."""
        df = load_electra_data(TEMP_ELECTRA)
        # The dismantled meter 'M-33333' must be excluded, leaving exactly 2 active rows
        self.assertEqual(len(df), 2)
        self.assertNotIn("M-33333", df["meter_number"].values)

    def test_electra_loader_strips_whitespace_and_renames(self):
        """Verify that load_electra_data strips spaces and outputs correct English schema."""
        df = load_electra_data(TEMP_ELECTRA)
        # Check if row index 1 was cleaned and available under 'meter_number'
        self.assertEqual(df.loc[1, "meter_number"], "M-22222")


if __name__ == "__main__":
    unittest.main(verbosity=2)