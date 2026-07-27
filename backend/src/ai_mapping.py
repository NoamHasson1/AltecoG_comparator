import json

import anthropic

SUGGESTION_MODEL = "claude-haiku-4-5"

# Keep in sync with DIRECT_FIELDS in frontend/static/main.js — these are the
# only fields an AI suggestion is scoped to (calculated fields are excluded).
DIRECT_FIELD_LABELS = {
    "billing_month": "Billing Month",
    "customer_id": "Customer ID",
    "customer_name": "Customer Name",
    "tax_id": "Customer Tax ID",
    "iec_contract": "Electricity Contract Number",
    "meter_number": "Meter Number",
    "voltage": "Voltage",
    "tou": "Energy Consumption (time-of-use / reading type)",
    "billing_type": "Billing Type",
    "tariff": "Tariff",
    "fixed_payment": "Fixed Payment",
    "contract_start_date": "Contract Start Date",
    "kva": "KVA",
}


def _field_result_schema():
    return {
        "anyOf": [
            {"type": "null"},
            {
                "type": "object",
                "properties": {
                    "sheet": {"type": "string"},
                    "column": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["sheet", "column", "reason"],
                "additionalProperties": False,
            },
        ]
    }


def _build_schema():
    keys = list(DIRECT_FIELD_LABELS.keys())
    return {
        "type": "object",
        "properties": {key: _field_result_schema() for key in keys},
        "required": keys,
        "additionalProperties": False,
    }


def _build_prompt(sheets):
    fields_desc = "\n".join(f"- {key}: {label}" for key, label in DIRECT_FIELD_LABELS.items())
    sheets_json = json.dumps(sheets, ensure_ascii=False)
    return f"""You are matching columns from a client's electricity billing export to a fixed set of target fields.

Target fields (key: description):
{fields_desc}

The client file has been inspected and its sheets/columns/sample rows are below as JSON. Each sheet has "name", "columns", and up to 3 "sample_rows".

{sheets_json}

For each target field, decide whether one column in the file clearly corresponds to it. Only suggest a match when you are reasonably confident based on the column name and/or its sample values. If no column is a good match, return null for that field. Never invent a sheet or column name that isn't in the data above.

For every match, give a one-sentence reason referencing the column name and/or sample values that justified the pick."""


def _clean_error_message(e):
    """Anthropic's SDK puts the readable message at body['error']['message'];
    e.message/str(e) is the full 'Error code: 400 - {...}' wrapper."""
    try:
        return e.body["error"]["message"]
    except (TypeError, KeyError):
        return e.message or str(e)


def suggest_field_mapping(sheets):
    """Ask Claude to suggest a field_mappings-shaped match for the 13 direct fields.

    Returns a dict keyed by field name, each value either None or
    {"sheet": ..., "column": ..., "reason": ...}.

    Raises RuntimeError with a short, user-facing message on any Anthropic API
    failure (bad key, no credits, rate limit, network) — the caller surfaces
    that message directly in the UI rather than a raw traceback.
    """
    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=SUGGESTION_MODEL,
            max_tokens=2048,
            output_config={"format": {"type": "json_schema", "schema": _build_schema()}},
            messages=[{"role": "user", "content": _build_prompt(sheets)}],
        )
    except anthropic.AuthenticationError:
        raise RuntimeError("The Anthropic API key is invalid. Double-check ANTHROPIC_API_KEY in .env.")
    except anthropic.PermissionDeniedError:
        raise RuntimeError("This Anthropic API key doesn't have permission to use this model.")
    except anthropic.RateLimitError:
        raise RuntimeError("Anthropic API rate limit reached — try again in a moment.")
    except anthropic.APIStatusError as e:
        # Covers things like "Your credit balance is too low..." (400) with
        # Anthropic's own message, which is already clear enough to show as-is.
        raise RuntimeError(_clean_error_message(e))
    except anthropic.APIConnectionError:
        raise RuntimeError("Could not reach the Anthropic API — check your network connection.")

    text = next(block.text for block in response.content if block.type == "text")
    return json.loads(text)
