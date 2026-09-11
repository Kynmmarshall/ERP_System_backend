"""Contract tests: every example payload must validate against its schema.

Run standalone with: pip install -r contracts/requirements.txt && pytest contracts/
Each service's own test suite additionally validates the *real* payloads it
produces/consumes against these same schema files (see services/*/tests).
"""
import json
from pathlib import Path

import pytest
from jsonschema import validate

EVENTS_DIR = Path(__file__).parent / "events"

CASES = [
    ("envelope.schema.json", "examples/enrollment-accepted.v1.example.json"),
    ("enrollment-accepted.v1.schema.json", "examples/enrollment-accepted.v1.example.json"),
]


def _load(relative_path: str) -> dict:
    return json.loads((EVENTS_DIR / relative_path).read_text(encoding="utf-8"))


@pytest.mark.parametrize("schema_file,example_file", CASES)
def test_example_matches_schema(schema_file: str, example_file: str) -> None:
    schema = _load(schema_file)
    example = _load(example_file)
    # The envelope schema validates the whole example; the payload schema
    # validates only the nested "data" object.
    target = example if schema_file == "envelope.schema.json" else example["data"]
    validate(instance=target, schema=schema)
