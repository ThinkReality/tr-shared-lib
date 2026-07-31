"""The lane rule: path decides infrastructure, and the default is to provision."""

from __future__ import annotations

import pytest

from tr_shared.testing.lanes import lane_for_path, run_needs_infrastructure


class TestLaneForPath:
    @pytest.mark.parametrize(
        "path",
        [
            "tests/unit/services/test_x.py",
            "tests/finance/unit/test_x.py",  # module-first layout
            "tests/architecture/test_guard.py",
            "tests/contracts/test_s2s.py",
        ],
    )
    def test_unit_paths(self, path: str) -> None:
        assert lane_for_path(path) == "unit"

    @pytest.mark.parametrize(
        "path",
        [
            "tests/integration/test_x.py",
            "tests/admin/integration/test_x.py",
            "tests/api/test_x.py",
            "tests/e2e/test_flow.py",
            "tests/integration/migrations/test_roundtrip.py",
        ],
    )
    def test_integration_paths(self, path: str) -> None:
        assert lane_for_path(path) == "integration"

    def test_unclassified_path_is_none(self) -> None:
        assert lane_for_path("tests/test_smoke.py") is None

    def test_integration_wins_a_tie(self) -> None:
        # Withholding infrastructure from a test that needs it fails confusingly
        # in someone else's suite; granting it costs seconds.
        assert lane_for_path("tests/integration/unit/test_x.py") == "integration"

    def test_windows_separators(self) -> None:
        assert lane_for_path(r"tests\unit\test_x.py") == "unit"


class TestRunNeedsInfrastructure:
    """An argument counts as a path only if it exists — see run_needs_infrastructure."""

    @pytest.fixture
    def tree(self, tmp_path):
        for d in ("tests/unit", "tests/architecture", "tests/integration", "tests/api"):
            (tmp_path / d).mkdir(parents=True)
        (tmp_path / "tests/unit/test_x.py").write_text("")
        return tmp_path

    def test_bare_pytest_provisions(self, tree) -> None:
        """No path arguments means collect everything."""
        assert run_needs_infrastructure([], root=tree) is True

    def test_flags_only_provisions(self, tree) -> None:
        assert run_needs_infrastructure(["-q", "--tb=short"], root=tree) is True

    def test_option_values_are_not_paths(self, tree) -> None:
        """`-p no:cacheprovider` used to force provisioning for every unit run."""
        assert (
            run_needs_infrastructure(
                ["tests/unit/", "-p", "no:cacheprovider", "-k", "some_name"], root=tree
            )
            is False
        )

    def test_unit_path_does_not_provision(self, tree) -> None:
        assert run_needs_infrastructure(["tests/unit/"], root=tree) is False

    def test_several_unit_paths_do_not_provision(self, tree) -> None:
        assert run_needs_infrastructure(["tests/unit/", "tests/architecture/"], root=tree) is False

    def test_one_integration_path_provisions(self, tree) -> None:
        assert run_needs_infrastructure(["tests/unit/", "tests/integration/"], root=tree) is True

    def test_unclassified_path_provisions(self, tree) -> None:
        """`pytest tests/` must provision — it collects the integration lane too."""
        assert run_needs_infrastructure(["tests/"], root=tree) is True

    def test_node_id_selector_is_stripped(self, tree) -> None:
        assert run_needs_infrastructure(["tests/unit/test_x.py::TestA::test_b"], root=tree) is False

    def test_flags_do_not_defeat_unit_detection(self, tree) -> None:
        assert run_needs_infrastructure(["-q", "-x", "tests/unit/"], root=tree) is False

    def test_marker_selection_without_paths_provisions(self, tree) -> None:
        """`pytest -m integration` with no path arguments collects everything."""
        assert run_needs_infrastructure([], "integration", root=tree) is True

    def test_marker_selection_over_an_integration_path_provisions(self, tree) -> None:
        assert run_needs_infrastructure(["tests/integration/"], "integration", root=tree) is True

    def test_marker_selection_over_a_mixed_path_set_provisions(self, tree) -> None:
        assert (
            run_needs_infrastructure(
                ["tests/unit/", "tests/integration/"], "integration", root=tree
            )
            is True
        )

    def test_marker_selection_over_only_unit_paths_does_not_provision(self, tree) -> None:
        """`pytest tests/unit/ -m integration` can select nothing, so provisioning it
        is guaranteed waste — a container started, migrated and waited on for a run
        with zero selectable tests.

        Safe because the lane marker is *derived from the path*
        (``plugin.pytest_collection_modifyitems``), so a test under a unit path
        cannot carry the integration marker. This used to return True, which cost
        tr-shared-lib's own unit lane ~90s per run and made it fail outright
        whenever the Docker daemon was busy.
        """
        assert run_needs_infrastructure(["tests/unit/"], "integration", root=tree) is False

    def test_marker_selection_over_only_unit_paths_still_respects_a_tie(self, tree) -> None:
        """`lane_for_path` resolves `integration` for a path carrying both segments,
        so this is not a unit-only path set and must still provision."""
        (tree / "tests/integration/unit").mkdir(parents=True)
        assert (
            run_needs_infrastructure(["tests/integration/unit/"], "integration", root=tree) is True
        )

    def test_negated_marker_does_not_provision(self, tree) -> None:
        assert run_needs_infrastructure(["tests/unit/"], "not integration", root=tree) is False
