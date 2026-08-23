from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.devstack.core.cmake_presets import ensure_basic_presets


class TestCMakePresets(unittest.TestCase):
    def test_ensure_basic_presets_creates_user_presets_with_ninja(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch("tools.devstack.core.cmake_presets.have_cmd", side_effect=lambda c: c == "ninja"):
                ensure_basic_presets(root)

            data = json.loads((root / "CMakeUserPresets.json").read_text(encoding="utf-8"))
            presets = {p["name"]: p for p in data.get("configurePresets", [])}
            self.assertIn("debug", presets)
            self.assertIn("release", presets)
            self.assertEqual("Ninja", presets["debug"].get("generator"))
            self.assertEqual("Ninja", presets["release"].get("generator"))

    def test_ensure_basic_presets_falls_back_to_make(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            def have(c: str) -> bool:
                return c == "make"

            with patch("tools.devstack.core.cmake_presets.have_cmd", side_effect=have):
                ensure_basic_presets(root)

            data = json.loads((root / "CMakeUserPresets.json").read_text(encoding="utf-8"))
            presets = {p["name"]: p for p in data.get("configurePresets", [])}
            self.assertEqual("Unix Makefiles", presets["debug"].get("generator"))
            self.assertEqual("Unix Makefiles", presets["release"].get("generator"))

    def test_ensure_basic_presets_requires_generator(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            def _die(_msg: str) -> None:
                raise SystemExit(1)

            with patch("tools.devstack.core.cmake_presets.have_cmd", side_effect=lambda _c: False), patch(
                "tools.devstack.core.cmake_presets.die", side_effect=_die
            ):
                with self.assertRaises(SystemExit):
                    ensure_basic_presets(root)
