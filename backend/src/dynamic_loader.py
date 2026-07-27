import json
import logging
import re
import pandas as pd

from .data_loader import STANDARD_SCHEMA, normalize_id_value

logger = logging.getLogger(__name__)


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
    # See data_loader.normalize_id_value — undoes the float artifact Excel
    # introduces for numeric-looking IDs (e.g. a blank cell elsewhere in the
    # column forces it to float64, so "377007686" round-trips as
    # 377007686.0 and would otherwise fail to match a clean string ID).
    return series.map(normalize_id_value)


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

    A field_mappings/billing_month entry may live on the "primary" sheet
    (whichever sheet meter_number is mapped from, one row per meter) or on
    the shared line-items sheet (one row per billing line, aggregated per
    customer) — no other sheet is supported for those, since there'd be no
    defined join key to reach it. Calculated fields are different: each one
    carries its own sheet + group_by_column, fully independent of the shared
    line-items sheet and of every other calculated field.
    """
    all_sheets = pd.read_excel(file_obj, sheet_name=None)
    logger.info(
        "CLIENT LOAD: read %d sheet(s): %s",
        len(all_sheets), {name: df.shape for name, df in all_sheets.items()},
    )
    logger.info("CLIENT LOAD: mapping in use:\n%s", json.dumps(mapping, ensure_ascii=False, indent=2))

    field_mappings = mapping.get("field_mappings", {})
    billing_month_cfg = mapping.get("billing_month")
    line_items_cfg = mapping.get("line_items")
    calculated_fields = mapping.get("calculated_fields", {})

    if "meter_number" not in field_mappings or "customer_id" not in field_mappings:
        raise ValueError("meter_number and customer_id must be mapped")

    primary_sheet_name = field_mappings["meter_number"]["sheet"]
    primary_df = all_sheets[primary_sheet_name].copy()

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

    # --- Calculated fields: each one is fully independent — its own sheet,
    # its own group-by column, its own value column and filters. Picking a
    # sheet for one calculated field has no effect on any other field, and
    # none of them share the field_mappings/billing_month line-items sheet
    # above (a calculated field may live on a completely different sheet).
    for target_key, rule in calculated_fields.items():
        calc_sheet_name = rule["sheet"]
        calc_group_by = rule["group_by_column"]
        calc_df = all_sheets[calc_sheet_name].copy()
        value_column = rule["value_column"]
        _column(calc_df, calc_sheet_name, value_column)
        _column(calc_df, calc_sheet_name, calc_group_by)
        filtered = _apply_filters(calc_df, calc_sheet_name, rule.get("filters", [])).copy()
        filtered[calc_group_by] = _normalize_id(filtered[calc_group_by])
        filtered[value_column] = pd.to_numeric(filtered[value_column], errors="coerce").fillna(0)
        summed = filtered.groupby(calc_group_by)[value_column].sum()
        result[target_key] = result["customer_id"].map(summed)
        logger.info(
            "CLIENT LOAD: calculated '%s' from sheet '%s' (%d/%d rows matched filters, "
            "%d distinct customers summed, %d customers with no matching rows -> NaN)",
            target_key, calc_sheet_name, len(filtered), len(calc_df), summed.shape[0],
            result[target_key].isna().sum(),
        )

    # Ensure every STANDARD_SCHEMA column exists (fill with None if missing),
    # same tail behavior as the fixed-format Alteco loader. Inserted all at
    # once via concat rather than one `result[col] = None` at a time, which
    # fragments the DataFrame and triggers a PerformanceWarning.
    missing_cols = [col for col in STANDARD_SCHEMA if col not in result.columns]
    if missing_cols:
        result = pd.concat([result, pd.DataFrame(None, index=result.index, columns=missing_cols)], axis=1)

    # meter_number isn't run through _normalize_id above (only customer_id is,
    # as the join key), so this is its only cleanup pass — use the same
    # float-artifact-safe normalization, not a naive astype(str).
    for col in ["meter_number", "customer_id"]:
        if col in result.columns:
            result[col] = result[col].map(normalize_id_value)

    final = result[STANDARD_SCHEMA]
    logger.info("CLIENT LOAD: final DataFrame has %d rows, %d columns", len(final), len(final.columns))
    logger.debug("CLIENT LOAD: final DataFrame (%d rows):\n%s", len(final), final.to_string())
    return final
