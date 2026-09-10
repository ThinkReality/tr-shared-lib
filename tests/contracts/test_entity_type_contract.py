"""Guards on the exported entity-type contract.

The point of the export is that no consumer has to hand-copy the taxonomy. That only
holds while the committed JSON tracks the enum, so the staleness test below is the
load-bearing one — without it the file is a snapshot with nothing checking it, which
is what the frontend's hand-copy already was.
"""

import json

from scripts.export_entity_type_contract import CONTRACT_PATH, build_contract, render
from tr_shared.contracts.entity_types import EntityType
from tr_shared.contracts.taxonomy import Feature


class TestEntityTypeContract:
    def test_the_contract_file_is_committed(self):
        assert CONTRACT_PATH.exists(), (
            f"{CONTRACT_PATH.name} is missing — run "
            "`uv run python scripts/export_entity_type_contract.py`"
        )

    def test_committed_file_matches_the_enum(self):
        assert CONTRACT_PATH.read_text(encoding="utf-8") == render(), (
            "contracts/entity-types.json is stale. Run "
            "`uv run python scripts/export_entity_type_contract.py` and commit the result."
        )

    def test_exports_every_entity_type_in_declaration_order(self):
        # Anchored on the enum rather than a hand-written expected list: a list here
        # would move with the contract on every addition and could never fail.
        assert build_contract()["entity_type"] == [member.value for member in EntityType]

    def test_exports_every_feature(self):
        assert build_contract()["feature"] == [member.value for member in Feature]

    def test_every_entity_types_feature_is_exported_too(self):
        # `EntityType.feature()` is the link between the two lists. A consumer that
        # filters by feature breaks if an entity's prefix is not in the feature list.
        features = set(build_contract()["feature"])

        unaccounted = sorted(
            member.value for member in EntityType if member.feature().value not in features
        )

        assert not unaccounted, f"entity types whose feature is not exported: {unaccounted}"

    def test_exports_no_labels(self):
        # Same rule as the lead contract: a label here would be a second spelling
        # authority. Fails on a shape change, not on a vocabulary change.
        contract = json.loads(render())

        for key in ("entity_type", "feature"):
            assert all(isinstance(value, str) for value in contract[key]), key
