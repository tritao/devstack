from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


DEVSTACK_PY = Path(__file__).resolve().parents[1] / "devstack.py"


@unittest.skipUnless(shutil.which("bwrap") and shutil.which("ccache") and shutil.which("cmake"), "requires bwrap, ccache, and cmake")
class TestSandboxBuild(unittest.TestCase):
    def test_identical_worktrees_share_stable_path_cache_entry(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            source_a = base / "source-a"
            source_b = base / "source-b"
            builds = base / "builds"
            cache = base / "ccache"
            source_a.mkdir()
            (source_a / "CMakeLists.txt").write_text(
                "cmake_minimum_required(VERSION 3.20)\nproject(stable_paths LANGUAGES CXX)\nadd_library(sample sample.cpp)\n"
            )
            (source_a / "sample.cpp").write_text("int stable_path_sample() { return 42; }\n")
            (source_a / "CMakePresets.json").write_text(
                json.dumps(
                    {
                        "version": 3,
                        "configurePresets": [
                            {
                                "name": "debug",
                                "generator": "Ninja",
                                "binaryDir": "${sourceDir}/build/debug",
                                "cacheVariables": {"CMAKE_BUILD_TYPE": "Debug"},
                            }
                        ],
                    }
                )
            )
            subprocess.run(["git", "init", "-q"], cwd=source_a, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=source_a, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=source_a, check=True)
            subprocess.run(["git", "add", "."], cwd=source_a, check=True)
            subprocess.run(["git", "commit", "-qm", "initial"], cwd=source_a, check=True)
            subprocess.run(["git", "worktree", "add", "--detach", str(source_b), "HEAD"], cwd=source_a, check=True, stdout=subprocess.DEVNULL)

            env = dict(os.environ)
            env.update({"DEVSTACK_BUILD_ROOT": str(builds), "CCACHE_DIR": str(cache)})
            subprocess.run(["ccache", "--zero-stats"], env=env, check=True, stdout=subprocess.DEVNULL)
            command = [
                "python3",
                str(DEVSTACK_PY),
                "build",
                "--preset",
                "debug",
                "--toolchain",
                "default",
                "--ccache-launcher",
                "--sandbox-paths",
                "--no-env-file",
            ]
            subprocess.run(command, cwd=source_a, env=env, check=True, stdout=subprocess.DEVNULL)
            subprocess.run(command, cwd=source_b, env=env, check=True, stdout=subprocess.DEVNULL)

            stats = subprocess.run(["ccache", "--show-stats"], env=env, check=True, capture_output=True, text=True)
            hit = re.search(r"^\s*Hits:\s+(\d+)", stats.stdout, flags=re.MULTILINE)
            self.assertIsNotNone(hit)
            self.assertGreaterEqual(int(hit.group(1)), 1)
            cache_a = builds / "source-a" / "sandbox" / "debug" / "CMakeCache.txt"
            cache_b = builds / "source-b" / "sandbox" / "debug" / "CMakeCache.txt"
            self.assertIn("CMAKE_HOME_DIRECTORY:INTERNAL=/tmp/devstack-build-env/src", cache_a.read_text())
            self.assertIn("CMAKE_HOME_DIRECTORY:INTERNAL=/tmp/devstack-build-env/src", cache_b.read_text())
