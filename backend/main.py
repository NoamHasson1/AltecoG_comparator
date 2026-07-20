import os
import pandas as pd
from src.data_loader import load_alteco_data, load_electra_data
from src.reconciliation_engine import ReconciliationEngine

def main():
    alteco_file = "data/AltecoG_Example.xlsx"
    electra_file = "data/Electra_Example.xlsx"
    output_report_path = "data/discrepancies_report.xlsx"
    
    print("Starting Altego Reconciliation Process...")
    
    print("Loading and cleaning input files...")
    df_alteco = load_alteco_data(alteco_file)
    df_electra = load_electra_data(electra_file)

    print(f"Rows loaded from Alteco: {len(df_alteco)}")
    print(f"Rows loaded from Electra: {len(df_electra)}")
    
    print("Running All Reconciliation Steps...")
    engine = ReconciliationEngine(df_alteco, df_electra)
    
    results = engine.run_all_steps()
    df_step1 = results["step1"]
    df_step2 = results["step2"]
    
    if not df_step1.empty or not df_step2.empty:
        total_errors = len(df_step1) + len(df_step2)
        print(f"Found {total_errors} mismatches! Saving report...")

        os.makedirs(os.path.dirname(output_report_path), exist_ok=True)
        
        with pd.ExcelWriter(output_report_path, engine='openpyxl') as writer:
            if not df_step1.empty:
                df_step1.to_excel(writer, index=False, sheet_name="Phase 1 - Metadata")
            if not df_step2.empty:
                df_step2.to_excel(writer, index=False, sheet_name="Phase 2 - Consumption")
                
        print(f"Success! Report saved to: {output_report_path}")
    else:
        print("Amazing! No mismatches found between the files.")

if __name__ == "__main__":
    main()