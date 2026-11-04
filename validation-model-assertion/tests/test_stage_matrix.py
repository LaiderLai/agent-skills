import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import validate_model as vm  # noqa: E402

IDS = {
    "pc": "UqFziVZDHLSyO3TqSWgNBoAdHbLI4dAH",
    "pc-kernel": "pYVQrBcKmBa0mZ4CCN7ExT6jH8rY1hza",
    "core24": "dwTAh7MZZ01zyriOZErqd1JynQLiOGvM",
    "snapd": "PMrrV4ml8uWuEUDBT8dSGnKUYbevVhc4",
}
TYPES = {"pc": "gadget", "pc-kernel": "kernel", "core24": "base", "snapd": "snapd"}


def make_model(grade: str, risk: str, **overrides) -> dict:
    tracks = {"pc": "24", "pc-kernel": "24", "core24": "latest", "snapd": "latest"}
    model = {
        "type": "model", "series": "16", "authority-id": "mybrand", "brand-id": "mybrand",
        "model": "my-model", "architecture": "amd64", "base": "core24", "grade": grade,
        "snaps": [{"name": n, "id": IDS[n], "type": TYPES[n],
                   "default-channel": f"{tracks[n]}/{risk}"} for n in IDS],
        "timestamp": "2026-10-07T00:00:00+00:00",
    }
    model.update(overrides)
    return model


def snap(model: dict, name: str) -> dict:
    return next(s for s in model["snaps"] if s["name"] == name)


def fake_store(kernel_risks=("edge",), kernel_id=None, kernel_resources=None):
    """Every snap is published on every risk, except the kernel's track 24.
    kernel_resources maps a risk to the component names published there."""
    def info(name, store_id=None):
        track = "24" if name in ("pc", "pc-kernel") else "latest"
        risks = kernel_risks if name == "pc-kernel" else vm.RISKS
        resources = (kernel_resources or {}) if name == "pc-kernel" else {}
        return {
            "snap-id": kernel_id if (name == "pc-kernel" and kernel_id) else IDS[name],
            "channel-map": [{"channel": {"track": track, "risk": r, "architecture": "amd64"},
                             "type": TYPES[name], "version": "1",
                             "resources": [{"name": c} for c in resources.get(r, [])]}
                            for r in risks],
        }
    return info


def run_store(model: dict, **store_kwargs) -> vm.Report:
    rep = vm.Report()
    with mock.patch.object(vm, "store_info", fake_store(**store_kwargs)), \
         mock.patch.object(vm, "resolution_scope", lambda *a, **k: ""):
        vm.check_store(model["snaps"], model, rep)
    return rep


class TestChannelSeverity(unittest.TestCase):
    def test_missing_risk_is_warning(self):
        rep = run_store(make_model("signed", "stable"))
        self.assertEqual(rep.errors, [])
        self.assertTrue(any("no release" in w["message"] for w in rep.warnings), rep.findings)

    def test_missing_track_is_warning(self):
        model = make_model("signed", "edge")
        snap(model, "pc-kernel")["default-channel"] = "99/stable"
        rep = run_store(model)
        self.assertEqual(rep.errors, [])
        self.assertTrue(any("does not exist" in w["message"] for w in rep.warnings), rep.findings)

    def test_snap_id_mismatch_still_error(self):
        rep = run_store(make_model("signed", "edge"), kernel_id="A" * 32)
        self.assertTrue(any("snap-id mismatch" in e["message"] for e in rep.errors), rep.findings)


def run_uc20(model: dict) -> vm.Report:
    rep = vm.Report()
    vm.check_uc20(model, rep, "uc20+")
    return rep


def with_components(components: dict, risk: str = "edge") -> dict:
    model = make_model("signed", risk)
    snap(model, "pc-kernel")["components"] = components
    return model


class TestComponentPublication(unittest.TestCase):
    def test_published_component_is_recorded(self):
        rep = run_store(with_components({"nvidia-ko": "required"}),
                        kernel_resources={"edge": ["nvidia-ko"]})
        self.assertEqual(rep.warnings, [])
        self.assertIn(("pc-kernel+nvidia-ko", "component published", "24/edge"), rep.lookups)
        header = vm.render_ledger(rep, online=True)[0]
        self.assertIn("4 of 4 snap-ids verified", header)
        self.assertIn("1 of 1 components published", header)

    def test_missing_required_component_warns(self):
        rep = run_store(with_components({"nvidia-ko": "required"}),
                        kernel_resources={"edge": ["other-ko"]})
        warns = [w for w in rep.warnings if "nvidia-ko" in w["message"]]
        self.assertEqual(len(warns), 1, rep.findings)
        self.assertIn(vm.UNPUBLISHED, warns[0]["fix"])
        self.assertEqual(rep.errors, [])

    def test_missing_optional_component_is_info(self):
        rep = run_store(with_components({"nvidia-ko": {"presence": "optional"}}),
                        kernel_resources={"edge": []})
        self.assertEqual(rep.warnings, [])
        self.assertTrue(any("nvidia-ko" in i["message"] for i in rep.findings
                            if i["level"] == "INFO"), rep.findings)

    def test_components_skipped_when_channel_unpublished(self):
        rep = run_store(with_components({"nvidia-ko": "required"}, risk="stable"),
                        kernel_resources={"edge": ["nvidia-ko"]})
        self.assertEqual(len(rep.warnings), 1, rep.findings)
        self.assertNotIn("nvidia-ko", rep.warnings[0]["message"])


class TestRiskSpelling(unittest.TestCase):
    def test_risk_typo_is_sign_error(self):
        model = make_model("signed", "stable")
        snap(model, "pc-kernel")["default-channel"] = "24/stble"
        errors = run_uc20(model).errors
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("invalid risk", errors[0]["message"])
        self.assertEqual(errors[0]["stage"], "sign")

    def test_risk_typo_not_reported_as_unpublished(self):
        model = make_model("signed", "stable")
        snap(model, "pc-kernel")["default-channel"] = "24/stble"
        rep = run_store(model, kernel_risks=vm.RISKS)
        self.assertFalse(any(vm.UNPUBLISHED in w["fix"] for w in rep.warnings), rep.findings)

    def test_branch_and_bare_forms_accepted(self):
        for channel in ("24/stable/hotfix", "edge", "24", "latest/beta"):
            model = make_model("signed", "stable")
            snap(model, "pc-kernel")["default-channel"] = channel
            self.assertEqual(run_uc20(model).errors, [], channel)

    def test_track_typo_is_error(self):
        for channel in ("2b/stable", "24-foo/stable", "lastest/edge", "stble"):
            model = make_model("signed", "stable")
            snap(model, "pc-kernel")["default-channel"] = channel
            errors = run_uc20(model).errors
            self.assertEqual(len(errors), 1, (channel, errors))
            self.assertIn("invalid track", errors[0]["message"])

    def test_documented_variant_track_is_warning(self):
        for channel in ("24-hwe/stable", "26-rt/edge", "22-oem/stable", "26.04/beta",
                        "24.10/stable", "classic-24.04/stable"):
            model = make_model("signed", "stable")
            snap(model, "pc-kernel")["default-channel"] = channel
            rep = run_uc20(model)
            self.assertEqual(rep.errors, [], channel)
            self.assertTrue(any("variant track" in w["message"] for w in rep.warnings),
                            (channel, rep.findings))

    def test_track_typo_not_reported_as_unpublished(self):
        model = make_model("signed", "stable")
        snap(model, "pc-kernel")["default-channel"] = "2b/stable"
        rep = run_store(model, kernel_risks=vm.RISKS)
        self.assertFalse(any(vm.UNPUBLISHED in w["fix"] for w in rep.warnings), rep.findings)

    def test_unknown_numeric_track_still_warning(self):
        model = make_model("signed", "stable")
        snap(model, "pc-kernel")["default-channel"] = "28/stable"
        self.assertEqual(run_uc20(model).errors, [])
        rep = run_store(model, kernel_risks=vm.RISKS)
        self.assertTrue(any(vm.UNPUBLISHED in w["fix"] for w in rep.warnings), rep.findings)


def run_stage(model: dict, filename: str) -> vm.Report:
    rep = vm.Report()
    vm.check_stage(model, os.path.join("/x", filename), rep)
    return rep


class TestStage(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(vm.parse_stage_name("/x/signed-next.json"), ("signed", "next"))
        self.assertIsNone(vm.parse_stage_name("model.json"))

    def test_consistent_file_clean(self):
        self.assertEqual(run_stage(make_model("signed", "beta"), "signed-next.json").findings, [])

    def test_grade_mismatch(self):
        rep = run_stage(make_model("dangerous", "beta"), "signed-next.json")
        self.assertEqual([e["where"] for e in rep.errors], ["grade"])

    def test_risk_mismatch(self):
        model = make_model("signed", "beta")
        snap(model, "pc-kernel")["default-channel"] = "24/edge"
        rep = run_stage(model, "signed-next.json")
        self.assertEqual([e["where"] for e in rep.errors], ['snaps "pc-kernel"'])
        self.assertIn("beta", rep.errors[0]["message"])

    def test_missing_channel(self):
        model = make_model("signed", "edge")
        del snap(model, "pc-kernel")["default-channel"]
        rep = run_stage(model, "signed-edge.json")
        self.assertEqual([e["where"] for e in rep.errors], ['snaps "pc-kernel"'])
        self.assertIn("edge", rep.errors[0]["message"])

    def test_non_convention_name_skipped(self):
        self.assertEqual(run_stage(make_model("dangerous", "edge"), "model.json").findings, [])

    def test_risk_typo_left_to_structural_check(self):
        model = make_model("signed", "stable")
        snap(model, "pc-kernel")["default-channel"] = "24/stble"
        self.assertEqual(run_stage(model, "signed-stable.json").findings, [])


def results_for(paths: list[str]) -> list[dict]:
    return [{"path": p, "model": make_model("signed", "edge"), "rep": vm.Report(), "fatal": None}
            for p in paths]


FULL_MATRIX = [f"/x/{g}-{s}.json" for g in ("dangerous", "signed", "secured")
               for s in ("edge", "next", "stable")]


class TestIdentity(unittest.TestCase):
    def test_full_matrix_not_collision(self):
        results = results_for(FULL_MATRIX)
        self.assertEqual(vm.check_identity_collisions(results), [])
        self.assertNotEqual(vm.describe_stage_matrices(results), [])

    def test_partial_matrix_not_collision(self):
        results = results_for(["/x/signed-edge.json", "/x/signed-next.json"])
        self.assertEqual(vm.check_identity_collisions(results), [])

    def test_mixed_names_still_collide(self):
        results = results_for(["/x/signed-edge.json", "/x/other.json"])
        self.assertNotEqual(vm.check_identity_collisions(results), [])

    def test_duplicate_cell_still_collides(self):
        results = results_for(["/a/signed-edge.json", "/b/signed-edge.json"])
        self.assertNotEqual(vm.check_identity_collisions(results), [])


class TestVerdicts(unittest.TestCase):
    def test_stage_mismatch_verdict_is_not_a_sign_failure(self):
        rep = run_stage(make_model("dangerous", "beta"), "signed-next.json")
        verdict = vm.compute_verdict(rep, "uc20+", online=True)
        self.assertNotIn("snap sign will reject", verdict)
        self.assertIn("<grade>-<stage>.json", verdict)

    def test_batch_with_unpublished_warning_is_not_plain_pass(self):
        results = results_for(["/x/signed-edge.json", "/x/signed-stable.json"])
        results[1]["rep"].warn('snaps "pc-kernel"', "channel '24/stable' has no release",
                               vm.UNPUBLISHED)
        for r in results:
            r.update(variant="uc20+", brand=None)
        out = vm.render_batch(results, online=True, summary=False)
        self.assertIn("PASS with warnings", out)
        self.assertIn("signed-stable.json", out.split("Verdict")[-1])

    def test_json_exit_code_counts_collisions(self):
        import json
        import subprocess
        import tempfile
        script = os.path.join(os.path.dirname(__file__), "..", "scripts", "validate_model.py")
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as d:
            for name in ("signed-edge.json", "other.json"):
                with open(os.path.join(d, name), "w") as fh:
                    json.dump(make_model("signed", "edge"), fh)
            proc = subprocess.run([sys.executable, script, d, "--json"],
                                  capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("stage_matrices", json.loads(proc.stdout))


if __name__ == "__main__":
    unittest.main()
