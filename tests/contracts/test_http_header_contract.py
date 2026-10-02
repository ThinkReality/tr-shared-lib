import json

from scripts.export_http_header_contract import CONTRACT_PATH, render
from tr_shared.contracts.headers import HttpHeader


class TestHttpHeaderContract:
    def test_committed_file_carries_every_header(self):
        committed = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        assert committed["http_header"] == {member.name: member.value for member in HttpHeader}

    def test_committed_file_is_exactly_what_the_exporter_writes(self):
        assert CONTRACT_PATH.read_text(encoding="utf-8") == render(), (
            "contracts/http-headers.json is stale. Run "
            "`.venv/bin/python scripts/export_http_header_contract.py` and commit the result."
        )
