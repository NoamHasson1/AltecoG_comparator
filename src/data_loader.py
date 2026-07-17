import pandas as pd

def load_alteco_data(file_path):
    """
    Loads the Alteco billing spreadsheet.
    Reads the 'חשבונית חוזה' sheet which contains the primary contract details.
    Cleans the unique identifier ('מספר מונה') to ensure reliable merging.
    """
    print(f"Loading Alteco data from: {file_path}")
    
    # Read the specific sheet containing 106 billing and metadata columns
    df = pd.read_excel(file_path, sheet_name="חשבונית חוזה")
    
    # Clean the meter number column by converting to string and stripping whitespace
    if "מספר מונה" in df.columns:
        df["מספר מונה"] = df["מספר מונה"].astype(str).str.strip()
        df = df[df["מספר מונה"] != ""]
    return df


def load_electra_metadata(file_path):
    """
    Loads the Electra client database sheet ('מצבת לקוחות').
    Filters out inactive/dismantled meters to avoid duplicate matching.
    Cleans the unique identifier ('מספר מונה').
    """
    print(f"Loading Electra client metadata from: {file_path}")
    
    # Read the sheet containing core client configuration details
    df = pd.read_excel(file_path, sheet_name="מצבת לקוחות")
    
    # Clean the meter number column to prevent format mismatch during join operations
    if "מספר מונה" in df.columns:
        df["מספר מונה"] = df["מספר מונה"].astype(str).str.strip()
        
    # Filter: Keep only meters where the status is 'פעיל' (Active)
    # This solves the meter replacement duplicates (e.g., active vs. dismantled)
    if "סטטוס מתקן" in df.columns:
        df = df[df["סטטוס מתקן"] == "פעיל"]
        
    return df


def load_electra_draft_lines(file_path):
    """
    Loads the raw Electra billing/usage details from the 'DRFT' sheet.
    This sheet contains the raw consumption and calculated financial charges.
    """
    print(f"Loading Electra billing draft lines from: {file_path}")
    
    # Read the raw transactional/billing data lines
    df = pd.read_excel(file_path, sheet_name="DRFT")
    
    return df