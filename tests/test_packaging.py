"""The Windows build pipeline: what it ships, and what it must never ship."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "build-windows.yml"
SPEC = REPO_ROOT / "packaging" / "tao_report_generator.spec"
GUIDE = REPO_ROOT / "packaging" / "使用說明.txt"
RELEASE_DOC = REPO_ROOT / "WINDOWS_RELEASE.md"

sys.path.insert(0, str(REPO_ROOT / "packaging"))
import verify_build  # noqa: E402

from app import paths  # noqa: E402


@pytest.fixture(scope="module")
def spec_code():
    """The spec with its explanatory docstring stripped.

    The docstring names the things that are deliberately left out, so grepping
    the whole file would match the very words it promises to exclude.
    """
    text = SPEC.read_text(encoding="utf-8")
    body = text.split('"""', 2)[-1]
    return "\n".join(
        line for line in body.splitlines() if not line.strip().startswith("#")
    )


@pytest.fixture(scope="module")
def spec():
    return SPEC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def guide():
    return GUIDE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def release_doc():
    return RELEASE_DOC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow():
    assert WORKFLOW.exists(), "the build workflow is missing"
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # PyYAML reads the bare key `on:` as the boolean True.
    doc["triggers"] = doc.get("on") or doc.get(True)
    return doc


class TestWorkflow:
    def test_it_can_be_started_by_hand(self, workflow):
        assert "workflow_dispatch" in workflow["triggers"]

    def test_a_version_tag_also_builds(self, workflow):
        assert "v*.*.*" in workflow["triggers"]["push"]["tags"]

    def test_it_builds_on_windows(self, workflow):
        assert workflow["jobs"]["build"]["runs-on"] == "windows-latest"

    def test_the_tests_run_before_the_build(self, workflow):
        names = [s.get("name", "") for s in workflow["jobs"]["build"]["steps"]]
        assert names.index("Run the test suite") < names.index("Build the application")

    def test_every_required_stage_is_present(self, workflow):
        names = " ".join(s.get("name", "") for s in workflow["jobs"]["build"]["steps"])
        for stage in ("Check out", "Set up Python", "Install dependencies",
                      "Run the test suite", "Build the application", "Verify the build",
                      "Package into a ZIP", "Upload the artifact"):
            assert stage in names, f"no step for {stage}"

    def test_the_artifact_is_named_as_agreed(self, workflow):
        assert workflow["env"]["ARTIFACT_NAME"] == "TAO-Report-Generator-Windows"
        upload = next(
            s for s in workflow["jobs"]["build"]["steps"]
            if s.get("uses", "").startswith("actions/upload-artifact")
        )
        assert upload["with"]["if-no-files-found"] == "error", (
            "an empty upload must fail the run, not pass quietly"
        )

    def test_the_gui_toolkit_can_start_headless(self, workflow):
        assert workflow["env"]["QT_QPA_PLATFORM"] == "offscreen"

    def test_nothing_may_open_a_dialog_on_the_build_machine(self, workflow):
        """A modal dialog on an unattended runner blocks until the job dies."""
        assert workflow["env"]["TAO_NO_DIALOGS"] == "1"
        assert str(workflow["env"]["CI"]).lower() == "true"

    def test_every_step_is_time_bounded(self, workflow):
        """One stalled step must not be able to consume the whole job."""
        job = workflow["jobs"]["build"]
        assert job["timeout-minutes"] <= 30
        for step in job["steps"]:
            if step.get("name") == "Summary":
                continue  # trivial, and runs even on failure
            assert "timeout-minutes" in step, f"{step.get('name')} is unbounded"

    def test_the_step_budget_leaves_room_under_the_job_limit(self, workflow):
        job = workflow["jobs"]["build"]
        budget = sum(s.get("timeout-minutes", 0) for s in job["steps"])
        assert budget >= job["timeout-minutes"], (
            "step limits should be able to fire before the job limit does"
        )

    def test_the_test_step_is_the_tightest_bound(self, workflow):
        """It caused the 45-minute timeout; it should fail fastest now."""
        steps = {s.get("name"): s for s in workflow["jobs"]["build"]["steps"]}
        assert steps["Run the test suite"]["timeout-minutes"] <= 12

    def test_the_test_run_reports_where_time_went(self, workflow):
        step = next(
            s for s in workflow["jobs"]["build"]["steps"]
            if s.get("name") == "Run the test suite"
        )
        assert "--durations" in step["run"], "a slow run must name the slow tests"
        assert "-vv" in step["run"], "a hang must name the last test to start"
        assert "--timeout" in step["run"]

    def test_pyinstaller_runs_exactly_once(self, workflow):
        runs = [
            s.get("run", "") for s in workflow["jobs"]["build"]["steps"]
        ]
        invocations = sum(r.count("pyinstaller ") for r in runs)
        assert invocations == 1, f"PyInstaller is invoked {invocations} times"

    def test_the_suite_is_not_run_twice(self, workflow):
        runs = " ".join(s.get("run", "") for s in workflow["jobs"]["build"]["steps"])
        assert runs.count("pytest") == 1, "one test run is enough"

    def test_dependencies_are_cached(self, workflow):
        setup = next(
            s for s in workflow["jobs"]["build"]["steps"]
            if s.get("uses", "").startswith("actions/setup-python")
        )
        assert setup["with"]["cache"] == "pip"
        assert "requirements-desktop.txt" in setup["with"]["cache-dependency-path"]

    def test_the_actions_are_current_major_versions(self, workflow):
        """Old majors run on retired Node runtimes and are warned about."""
        minimum = {"actions/checkout": 5, "actions/setup-python": 6,
                   "actions/upload-artifact": 5}
        for step in workflow["jobs"]["build"]["steps"]:
            uses = step.get("uses", "")
            if not uses:
                continue
            name, _, ref = uses.partition("@")
            if name in minimum:
                assert int(ref.lstrip("v").split(".")[0]) >= minimum[name], (
                    f"{uses} is an outdated major version"
                )

    def test_the_smoke_test_is_bounded(self, workflow):
        step = next(
            s for s in workflow["jobs"]["build"]["steps"]
            if s.get("name") == "Verify the build"
        )
        assert step["timeout-minutes"] <= 6
        assert 60 <= int(step["env"]["TAO_SELFTEST_TIMEOUT"]) <= 300

    def test_it_needs_no_secrets(self):
        assert "secrets." not in WORKFLOW.read_text(encoding="utf-8"), (
            "a build of an offline tool should need no credentials"
        )

    def test_it_only_reads_the_repository(self, workflow):
        assert workflow["permissions"] == {"contents": "read"}


class TestSpec:
    def test_it_builds_a_folder_not_a_single_file(self, spec):
        assert "COLLECT(" in spec, "--onedir means a COLLECT step"
        assert "exclude_binaries=True" in spec

    def test_the_end_user_gets_no_console_window(self, spec):
        assert "console=False" in spec

    def test_no_company_data_is_bundled(self, spec_code):
        for forbidden in ("samples", "ground_truth", "decisions.json", "settings.json"):
            assert forbidden not in spec_code, f"{forbidden} must not be packaged"

    def test_the_seed_configuration_travels_with_the_app(self, spec):
        assert "operator_mapping.json" in spec
        assert "report_scope.json" in spec

    def test_the_development_interface_is_excluded(self, spec):
        assert '"streamlit"' in spec, "the desktop build should not carry Streamlit"

    def test_the_entry_point_is_the_desktop_app(self, spec):
        assert 'desktop" / "main.py"' in spec


class TestVerifier:
    def test_it_rejects_a_folder_that_is_not_there(self, tmp_path):
        verify_build.failures.clear()
        assert verify_build.main([str(tmp_path / "nope")]) == 1

    def test_it_rejects_a_folder_with_no_executable(self, tmp_path):
        verify_build.failures.clear()
        (tmp_path / "something.txt").write_text("x")
        assert verify_build.main([str(tmp_path)]) == 1

    def test_it_refuses_a_build_carrying_a_company_workbook(self):
        assert any(
            pattern == "*.xlsx" for pattern, _ in verify_build.FORBIDDEN_PATTERNS
        ), "a build containing a workbook must be rejected"

    def test_it_checks_the_packaged_engine_actually_runs(self):
        source = (REPO_ROOT / "packaging" / "verify_build.py").read_text(encoding="utf-8")
        assert "--selftest" in source

    def test_it_does_not_claim_the_interface_was_tested(self):
        source = (REPO_ROOT / "packaging" / "verify_build.py").read_text(encoding="utf-8")
        assert "not claimed as tested" in source or "not opened" in source


class TestEndUserGuide:
    def test_a_short_chinese_guide_ships_with_the_app(self, guide):
        chinese = sum(1 for ch in guide if "一" <= ch <= "鿿")
        assert chinese > 200
        assert len(guide.splitlines()) < 90, "it is meant to be short"

    def test_it_avoids_developer_terminology(self, guide):
        for word in ("Python", "Streamlit", "Git", "pip", "PyInstaller", "terminal"):
            assert word.lower() not in guide.lower(), f"{word} means nothing to the user"

    def test_it_says_the_data_stays_local(self, guide):
        assert "不會上傳" in guide

    def test_it_warns_against_copying_only_the_exe(self, guide):
        assert "不能只複製" in guide


class TestReleaseDoc:
    def test_it_names_the_workflow_to_click(self, release_doc, workflow):
        assert workflow["name"] in release_doc

    def test_it_says_where_the_zip_appears(self, release_doc):
        assert "Artifacts" in release_doc
        assert "TAO-Report-Generator-Windows" in release_doc

    def test_it_explains_tagging(self, release_doc):
        assert "git tag v0.1.0" in release_doc

    def test_it_warns_about_sending_only_the_exe(self, release_doc):
        assert "not just the `.exe`" in release_doc

    def test_it_records_that_streamlit_is_development_only(self, release_doc):
        assert "development only" in release_doc


class TestPaths:
    def test_in_a_checkout_everything_stays_in_the_repo(self):
        assert not paths.is_frozen()
        assert paths.user_data_dir() == REPO_ROOT / "config"
        assert paths.seed_config_dir() == REPO_ROOT / "config"

    def test_a_packaged_app_writes_user_data_outside_itself(self, monkeypatch, tmp_path):
        """Otherwise an upgrade would wipe the user's saved decisions."""
        monkeypatch.setattr(paths, "is_frozen", lambda: True)
        monkeypatch.setattr(paths, "bundle_dir", lambda: tmp_path / "app")
        monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
        monkeypatch.setattr(sys, "platform", "win32")

        data = paths.user_data_dir()
        assert data.is_dir()
        assert (tmp_path / "app") not in data.parents and data != tmp_path / "app"

    def test_the_shipped_config_is_used_until_the_user_has_their_own(
        self, monkeypatch, tmp_path
    ):
        seed = tmp_path / "bundle" / "config"
        seed.mkdir(parents=True)
        (seed / "operator_mapping.json").write_text("{}", encoding="utf-8")
        user = tmp_path / "user"
        user.mkdir()

        monkeypatch.setattr(paths, "seed_config_dir", lambda: seed)
        monkeypatch.setattr(paths, "user_data_dir", lambda: user)

        assert paths.resolve_config("operator_mapping.json") == seed / "operator_mapping.json"
        (user / "operator_mapping.json").write_text("{}", encoding="utf-8")
        assert paths.resolve_config("operator_mapping.json") == user / "operator_mapping.json"

    def test_an_unwritable_location_does_not_lose_the_decisions(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(paths, "is_frozen", lambda: True)
        monkeypatch.setattr(paths, "bundle_dir", lambda: tmp_path)
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setenv("APPDATA", str(tmp_path / "blocked"))
        monkeypatch.setattr(
            Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(OSError("denied"))
        )
        assert paths.user_data_dir() == tmp_path / "config"


class TestGitignore:
    def test_build_output_is_not_committed(self):
        text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        for entry in ("dist/", "build/", "settings.json"):
            assert entry in text, f"{entry} should not be committed"
