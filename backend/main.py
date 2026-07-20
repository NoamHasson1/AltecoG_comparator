import os
import pandas as pd
from src.data_loader import load_alteco_data, load_electra_data
from src.reconciliation_engine import ReconciliationEngine

def main():
    """
    This script runs the reconciliation process from the command line.
    For the web-based UI version, please run `app.py`.
    """

    # 1. Define paths to your input data files
    alteco_file = "data/AltecoG_Example.xlsx"
    electra_file = "data/Electra_Example.xlsx"
    
    # Define where to save the output report
    output_report_path = "data/discrepancies_report.xlsx"
    
    print("Starting Altego Reconciliation Process...")
    
    # 2. Load and standardize data using the data_loader
    print("Loading and cleaning input files...")
    df_alteco = load_alteco_data(alteco_file)
    df_electra = load_electra_data(electra_file)

    print(f"Rows loaded from Alteco: {len(df_alteco)}")
    print(f"Rows loaded from Electra: {len(df_electra)}")
    
    # 3. Initialize the Engine and run Step 1 comparison
    print("Running Step 1 - Commercial Metadata Verification...")
    engine = ReconciliationEngine(df_alteco, df_electra)
    df_errors = engine.run_step_1_metadata()
    
    # 4. Save results to a physical Excel file if errors were found
    if not df_errors.empty:
        print(f"Found {len(df_errors)} mismatches! Saving report...")

        # Ensure the data/ directory exists before writing
        os.makedirs(os.path.dirname(output_report_path), exist_ok=True)
        
        # Write the Pandas DataFrame directly into a clean Excel sheet
        df_errors.to_excel(output_report_path, index=False, sheet_name="Metadata Mismatches")
        print(f"Success! Report saved to: {output_report_path}")
    else:
        print("Amazing! No metadata mismatches found between the files.")

if __name__ == "__main__":
    main()