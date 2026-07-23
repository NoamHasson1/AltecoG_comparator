import re
import pandas as pd

from .data_loader import STANDARD_SCHEMA


def inspect_workbook(file_obj):
    """
    Reads every sheet in an uploaded workbook and returns its shape (sheet
    names, columns, and a couple of sample rows) so the mapping UI can show
    real values as a guide while the user maps fields.
    """
    all_sheets = pd.read_excel(file_obj, sheet_name=None, nrows=3)
    sheets = []
    for name, df in all_sheets.items():
        clean = df.replace({pd.NaT: None, pd.NA: None, float('nan'): None})
        sheets.append({
            "name": name,
            "columns": list(df.columns),
            "sample_rows": clean.to_dict(orient="records")
        })
    return {"sheets": sheets}


def _normalize_id(series):
    return series.astype(str).str.strip()


def _column(df, sheet_name, column):
    """
    Fetches a mapped column, raising a clear error if it doesn't exist rather
    than a raw KeyError or (worse) silently treating the field as unmapped —
    a wrong mapping should fail loudly, not quietly produce all-None data.
    """
    if column not in df.columns:
        raise ValueError(f"Column '{column}' not found on sheet '{sheet_name}'. Check the mapping.")
    return df[column]


def _apply_filters(df, sheet_name, filters):
    """ANDs together a list of {column, match_type, values} conditions."""
    mask = pd.Series(True, index=df.index)
    for f in filters:
        column, match_type, values = f["column"], f["match_type"], f["values"]
        col = _column(df, sheet_name, column).astype(str)
        if match_type == "equals":
            mask &= col.str.strip() == str(values[0]).strip()
        elif match_type == "contains_any":
            pattern = "|".join(re.escape(v) for v in values)
            mask &= col.str.contains(pattern, na=False, regex=True)
        else:
            raise ValueError(f"Unknown match_type: {match_type}")
    return df[mask]


def _resolve_per_customer_column(line_items_df, sheet_name, group_by_column, column):
    """First value of `column` per customer, for fields that live on the line-items sheet."""
    _column(line_items_df, sheet_name, column)
    # Normalize the join key to string — an all-numeric-looking ID column (e.g. "377001")
    # can round-trip through Excel as int64, which would silently fail to .map() against
    # the string-normalized customer_id on the primary sheet otherwise.
    keys = _normalize_id(line_items_df[group_by_column])
    return line_items_df[column].groupby(keys).first()


def load_mapped_data(file_obj, mapping):
    """
    Generic replacement for a client-specific loader: builds a STANDARD_SCHEMA
    dataframe entirely from a user-configured mapping instead of hardcoded
    column names. See backend/mappings/electra_default.json for an example.

    A field may live on the "primary" sheet (whichever sheet meter_number is
    mapped from, one row per meter) or on the line-items sheet (one row per
    billing line, aggregated per customer) — no other sheet is supported per
    field, since there'd be no defined join key to reach it.
    """
    all_sheets = pd.read_excel(file_obj, sheet_name=None)

    field_mappings = mapping.get("field_mappings", {})
    active_filter = mapping.get("active_filter")
    billing_month_cfg = mapping.get("billing_month")
    line_items_cfg = mapping.get("line_items")
    calculated_fields = mapping.get("calculated_fields", {})

    if "meter_number" not in field_mappings or "customer_id" not in field_mappings:
        raise ValueError("meter_number and customer_id must be mapped")

    primary_sheet_name = field_mappings["meter_number"]["sheet"]
    primary_df = all_sheets[primary_sheet_name].copy()

    if active_filter:
        col, val = active_filter["column"], active_filter["value"]
        primary_df = primary_df[_normalize_id(_column(primary_df, primary_sheet_name, col)) == str(val).strip()]

    line_items_sheet_name = line_items_cfg["sheet"] if line_items_cfg else None
    line_items_df = all_sheets[line_items_sheet_name].copy() if line_items_sheet_name else None
    group_by_column = line_items_cfg["group_by_column"] if line_items_cfg else None
    if line_items_df is not None:
        _column(line_items_df, line_items_sheet_name, group_by_column)

    # customer_id must live on the primary sheet — it's the anchor used to join
    # in any fields that live on the line-items sheet instead.
    customer_id_cfg = field_mappings["customer_id"]
    if customer_id_cfg["sheet"] != primary_sheet_name:
        raise ValueError("customer_id must be mapped from the same sheet as meter_number")
    primary_df["__customer_id__"] = _normalize_id(_column(primary_df, primary_sheet_name, customer_id_cfg["column"]))

    result = pd.DataFrame(index=primary_df.index)
    result["customer_id"] = primary_df["__customer_id__"]

    for target_key, cfg in field_mappings.items():
        if target_key == "customer_id":
            continue
        sheet_name, column = cfg["sheet"], cfg["column"]
        if sheet_name == primary_sheet_name:
            result[target_key] = _column(primary_df, sheet_name, column).values
        elif sheet_name == line_items_sheet_name:
            per_customer = _resolve_per_customer_column(line_items_df, sheet_name, group_by_column, column)
            result[target_key] = primary_df["__customer_id__"].map(per_customer)
        else:
            raise ValueError(
                f"Field '{target_key}' references sheet '{sheet_name}', which is neither "
                "the primary sheet (from meter_number's mapping) nor the line-items sheet."
            )

    # --- Billing month: either a direct column, or derived from a date column ---
    if billing_month_cfg:
        mode = billing_month_cfg.get("mode", "direct")
        sheet_name, column = billing_month_cfg["sheet"], billing_month_cfg["column"]
        if sheet_name == primary_sheet_name:
            raw = _column(primary_df, sheet_name, column)
        elif sheet_name == line_items_sheet_name:
            raw = primary_df["__customer_id__"].map(
                _resolve_per_customer_column(line_items_df, sheet_name, group_by_column, column)
            )
        else:
            raise ValueError(f"billing_month references unknown sheet '{sheet_name}'")

        if mode == "derive_from_date":
            result["billing_month"] = pd.to_datetime(raw, errors="coerce").dt.strftime("%Y-%m")
        else:
            result["billing_month"] = raw.values if hasattr(raw, "values") else raw

    # --- Calculated fields: aggregated from the line-items sheet, per customer ---
    if line_items_df is not None:
        for target_key, rule in calculated_fields.items():
            value_column = rule["value_column"]
            _column(line_items_df, line_items_sheet_name, value_column)
            filtered = _apply_filters(line_items_df, line_items_sheet_name, rule.get("filters", [])).copy()
            filtered[group_by_column] = _normalize_id(filtered[group_by_column])
            filtered[value_column] = pd.to_numeric(filtered[value_column], errors="coerce").fillna(0)
            summed = filtered.groupby(group_by_column)[value_column].sum()
            result[target_key] = result["customer_id"].map(summed)

    # Ensure every STANDARD_SCHEMA column exists (fill with None if missing),
    # same tail behavior as the fixed-format Alteco loader.
    for col in STANDARD_SCHEMA:
        if col not in result.columns:
            result[col] = None

    for col in ["meter_number", "customer_id"]:
        if col in result.columns:
            result[col] = result[col].astype(str).str.strip()

    return result[STANDARD_SCHEMA]
