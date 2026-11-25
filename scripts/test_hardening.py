"""Fail-closed hardening regression tests for scripts/verify_lattice.py and scripts/verify_convergences.py.

Standard-library Python 3 only (Apache-2.0), zero bare `assert` statements so `-O` strips nothing.
Run across all three isolated modes:
    python3 -I -B scripts/test_hardening.py -v
    python3 -I -O -B scripts/test_hardening.py -v
    python3 -I -B -W error scripts/test_hardening.py -v
"""

from __future__ import annotations

import ast
import copy
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import verify_convergences as vc  # noqa: E402
import verify_lattice as vl  # noqa: E402


class TestPerBankRmsNormHardening(unittest.TestCase):
    """Non-vacuous per-bank RMSNorm isolation and mutation-kill checks."""

    def test_perbank_executes_slot_slice_and_isolates_base(self) -> None:
        res = vl.run_shared_token_and_rmsnorm_experiment()
        self.assertGreater(res["global_rmsnorm_base_bleed"], 0.15)
        self.assertAlmostEqual(res["global_rmsnorm_base_bleed"], res["predicted_global_bleed"], places=12)
        self.assertGreater(res["perbank_slot_on_norm"], 1.0)
        self.assertEqual(res["perbank_rmsnorm_base_bleed"], 0.0)

    def test_global_norm_mutation_is_killed_by_perbank_experiment(self) -> None:
        """Swapping per_bank_rms_norm for global rms_norm must cause non-zero bleed."""
        def _leaky_global(v, bank_sizes, eps=1e-5):
            return vl.rms_norm(v, eps=eps)

        with mock.patch.object(vl, "per_bank_rms_norm", side_effect=_leaky_global):
            mutated = vl.run_shared_token_and_rmsnorm_experiment()
        self.assertGreater(mutated["perbank_rmsnorm_base_bleed"], 0.15)
        self.assertAlmostEqual(
            mutated["perbank_rmsnorm_base_bleed"],
            mutated["global_rmsnorm_base_bleed"],
            places=12,
        )

    def test_rmsnorm_and_perbank_fail_closed_on_invalid_inputs(self) -> None:
        with self.assertRaises(ValueError):
            vl.rms_norm([])
        for bad_eps in (0.0, -1e-5, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                vl.rms_norm([1.0, 2.0], eps=bad_eps)
        for bad_vec in ([float("nan"), 1.0], [float("inf"), 1.0], [True, 1.0]):
            with self.assertRaises(ValueError):
                vl.rms_norm(bad_vec)

        with self.assertRaises(ValueError):
            vl.per_bank_rms_norm([1.0, 2.0], ())
        with self.assertRaises(ValueError):
            vl.per_bank_rms_norm([1.0, 2.0, 3.0], (2, 2))
        with self.assertRaises(ValueError):
            vl.per_bank_rms_norm([1.0, 2.0], (0, 2))
        with self.assertRaises(ValueError):
            vl.per_bank_rms_norm([1.0, 2.0], (True, 1))


class TestCapabilityTagAndManifestHardening(unittest.TestCase):
    """128-bit capability tag width, canonical framing, and fail-closed manifest validation."""

    def test_capability_tags_are_128bit_lowercase_hex_and_rotation_sensitive(self) -> None:
        self.assertEqual(vc.CAPABILITY_TAG_HEX_LEN, 32)
        out = vc.compile_vertical_zone_manifest(vc.STANDARD_ZONE_MANIFEST)
        tags = out["l1_loom"]
        self.assertEqual(len(tags), 5)
        self.assertEqual(len(set(tags.values())), 5)
        for tag in tags.values():
            self.assertEqual(len(tag), 32)
            self.assertTrue(all(ch in "0123456789abcdef" for ch in tag))

        mutated = copy.deepcopy(vc.STANDARD_ZONE_MANIFEST)
        mutated["plane1_tree_sha256"] = "c" * 64
        out_mut = vc.compile_vertical_zone_manifest(mutated)
        for z in vc.STANDARD_ZONE_MANIFEST["zones"]:
            self.assertNotEqual(tags[z], out_mut["l1_loom"][z])

    def test_colon_bearing_zone_names_have_unambiguous_tags(self) -> None:
        m = {
            "plane1_tree_sha256": "a" * 64,
            "zones": ["a:0", "a"],
            "adapters": ["ad0"],
            "zone_predicates": {"a:0": ["p1"], "a": ["p2"]},
            "precedence": {"a:0": {"ad0": 1}, "a": {"ad0": 1}},
        }
        out = vc.compile_vertical_zone_manifest(m)
        self.assertEqual(len(set(out["l1_loom"].values())), 2)
        for tag in out["l1_loom"].values():
            self.assertEqual(len(tag), 32)

    def test_bool_and_float_precedence_values_fail_closed(self) -> None:
        for bad_val in (True, False, 1.0, 0.0, 2, -1, "1", None):
            m = copy.deepcopy(vc.STANDARD_ZONE_MANIFEST)
            m["precedence"]["prose"]["corpus_prose"] = bad_val
            with self.assertRaises(ValueError):
                vc.compile_vertical_zone_manifest(m)

    def test_duplicate_or_mismatched_manifest_fields_fail_closed(self) -> None:
        dup_zone = copy.deepcopy(vc.STANDARD_ZONE_MANIFEST)
        dup_zone["zones"] = ["prose", "prose"]
        with self.assertRaises(ValueError):
            vc.compile_vertical_zone_manifest(dup_zone)

        dup_adapter = copy.deepcopy(vc.STANDARD_ZONE_MANIFEST)
        dup_adapter["adapters"] = ["corpus_prose", "corpus_prose"]
        with self.assertRaises(ValueError):
            vc.compile_vertical_zone_manifest(dup_adapter)

        bad_sha = copy.deepcopy(vc.STANDARD_ZONE_MANIFEST)
        bad_sha["plane1_tree_sha256"] = "not-a-sha"
        with self.assertRaises(ValueError):
            vc.compile_vertical_zone_manifest(bad_sha)

        extra_prec = copy.deepcopy(vc.STANDARD_ZONE_MANIFEST)
        extra_prec["precedence"]["shadow_zone"] = {a: 0 for a in extra_prec["adapters"]}
        with self.assertRaises(ValueError):
            vc.compile_vertical_zone_manifest(extra_prec)

        extra_adapter = copy.deepcopy(vc.STANDARD_ZONE_MANIFEST)
        extra_adapter["precedence"]["prose"]["shadow_adapter"] = 1
        with self.assertRaises(ValueError):
            vc.compile_vertical_zone_manifest(extra_adapter)

        missing_pred = copy.deepcopy(vc.STANDARD_ZONE_MANIFEST)
        del missing_pred["zone_predicates"]["code"]
        with self.assertRaises(ValueError):
            vc.compile_vertical_zone_manifest(missing_pred)

    def test_canonical_sha256_rejects_non_finite_floats(self) -> None:
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValueError):
                vc.canonical_sha256({"x": bad})


class TestZeroBareAsserts(unittest.TestCase):
    """Ensure -O cannot strip any check in modified/added loom scripts."""

    def test_zero_bare_assert_statements(self) -> None:
        for name in ("verify_lattice.py", "verify_convergences.py", "test_hardening.py"):
            tree = ast.parse((SCRIPTS_DIR / name).read_text(encoding="utf-8"))
            count = sum(isinstance(node, ast.Assert) for node in ast.walk(tree))
            self.assertEqual(count, 0, f"{name} contains {count} bare assert statements")


if __name__ == "__main__":
    unittest.main()
