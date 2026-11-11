"""The single-file executable: its name, its launchers, its build and its release workflow.

The executable itself is never started here - ``build-exe.py`` does that after every build.
These tests pretend to be frozen and check that nothing in that mode points at files that only
exist inside the unpacked archive, and that the build script and the workflow agree on names.

Run: python3 -m unittest discover -s tests
"""

import importlib.util
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from nudge import __build__, __version__, autostart, desktop_entry, paths  # noqa: E402
from nudge.ui import window_icon  # noqa: E402

#: How the Loresoft site reads a release asset: <app>-<os>-<arch>-<version>[-build<build>][.exe]
ASSET_PATTERN = re.compile(r"^nudge-(linux|windows)-[a-z0-9_]+-\d+\.\d+\.\d+(-build\d+)?(\.exe)?$")


def _build_script():
    """Import ``build-exe.py`` (its name is not a module name)."""
    spec = importlib.util.spec_from_file_location("build_exe", str(ROOT / "build-exe.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestExecutableName(unittest.TestCase):
    def setUp(self):
        self.build = _build_script()

    def test_the_name_carries_platform_and_version(self):
        cases = [
            (False, "x86_64", "nudge-linux-x86_64-1.2.0-build3"),
            (False, "aarch64", "nudge-linux-aarch64-1.2.0-build3"),
            (True, "AMD64", "nudge-windows-x86_64-1.2.0-build3.exe"),
        ]
        for windows, machine, expected in cases:
            with self.subTest(machine=machine, windows=windows), \
                    patch.object(self.build, "IS_WINDOWS", windows), \
                    patch.object(self.build.platform, "machine", return_value=machine):
                name = self.build.executable_name("1.2.0", 3)
                self.assertEqual(name, expected)
                self.assertRegex(name, ASSET_PATTERN)

    def test_the_name_defaults_to_this_version(self):
        self.assertIn("-{0}-build{1}".format(__version__, __build__), self.build.executable_name())


class TestFrozenLaunchers(unittest.TestCase):
    """A launcher written by the executable must start the executable, not a script."""

    def test_a_clone_is_started_through_its_launcher_script(self):
        with patch.object(paths, "IS_FROZEN", False):
            self.assertEqual(paths.launcher_arguments(), [str(paths.LAUNCHER_SCRIPT)])
            self.assertEqual(paths.launcher_directory(), paths.PROJECT_ROOT)

    def test_the_executable_is_started_without_arguments(self):
        with patch.object(paths, "IS_FROZEN", True), \
                patch.object(sys, "executable", "/opt/nudge/nudge-linux-x86_64-1.2.0-build3"):
            self.assertEqual(paths.launcher_arguments(), [])
            self.assertEqual(paths.launcher_directory(), Path("/opt/nudge"))
            self.assertEqual(autostart._launch_command(), '"/opt/nudge/nudge-linux-x86_64-1.2.0-build3"')
            entry = desktop_entry.build_entry("nudge")
        self.assertIn('Exec="/opt/nudge/nudge-linux-x86_64-1.2.0-build3"\n', entry)
        self.assertIn("Path=/opt/nudge\n", entry)

    def test_a_clone_entry_is_unchanged(self):
        with patch.object(paths, "IS_FROZEN", False):
            entry = desktop_entry.build_entry("nudge")
        self.assertIn('Exec="{0}" "{1}"\n'.format(paths.python_command(), paths.LAUNCHER_SCRIPT), entry)

    def test_icons_are_never_written_into_the_unpacked_files(self):
        with patch.object(window_icon, "IS_FROZEN", True):
            self.assertEqual(window_icon.icon_directories(), [paths.cache_dir()])


class TestBuild(unittest.TestCase):
    def setUp(self):
        self.build = _build_script()

    def test_the_spec_carries_the_translations_and_names_the_platform(self):
        with patch.object(self.build, "IS_WINDOWS", False), patch.object(self.build, "IS_LINUX", True):
            text = self.build.spec_text()
        self.assertIn("locales", text)
        self.assertIn("'Xlib'", text)
        self.assertIn("console=False", text)
        self.assertNotIn(".exe", text)

    def test_windows_does_not_collect_xlib(self):
        with patch.object(self.build, "IS_WINDOWS", True), patch.object(self.build, "IS_LINUX", False), \
                patch.object(self.build, "windows_icon", return_value=None):
            text = self.build.spec_text()
        self.assertNotIn("Xlib", text)
        self.assertNotIn(".exe", text.split("name=")[1].split(",")[0])

    def test_the_entry_script_compiles_and_gives_children_the_system_library_path(self):
        template = self.build.ENTRY_TEMPLATE
        compile(template, "entry.py", "exec")
        head = template.split("if getattr(sys")[0]
        namespace = {}
        exec(head, namespace)
        with patch.dict(os.environ, {"LD_LIBRARY_PATH": "/tmp/_MEI1", "LD_LIBRARY_PATH_ORIG": "/usr/lib/x"}):
            namespace["use_system_library_path"]()
            if sys.platform.startswith("linux"):
                self.assertEqual(os.environ["LD_LIBRARY_PATH"], "/usr/lib/x")
        with patch.dict(os.environ, {"LD_LIBRARY_PATH": "/tmp/_MEI1"}):
            os.environ.pop("LD_LIBRARY_PATH_ORIG", None)
            namespace["use_system_library_path"]()
            if sys.platform.startswith("linux"):
                self.assertNotIn("LD_LIBRARY_PATH", os.environ)

    def test_every_data_file_exists(self):
        for source, _target in self.build.DATA_FILES:
            self.assertTrue((ROOT / source).exists(), source)

    def test_build_output_is_ignored_by_git(self):
        lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("/build/", lines)
        self.assertIn("/dist/", lines)


class TestWorkflow(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / ".github" / "workflows" / "release-exe.yml").read_text(encoding="utf-8")

    def test_it_builds_on_both_systems(self):
        self.assertIn("ubuntu-22.04", self.text)
        self.assertIn("windows-latest", self.text)

    def test_the_release_is_tagged_with_version_and_build(self):
        self.assertIn('TAG="v${VERSION}-build${BUILD}"', self.text)
        self.assertIn("build-exe.py --print-version", self.text)

    def test_it_uploads_what_the_build_writes(self):
        self.assertIn("dist/nudge-*", self.text)


if __name__ == "__main__":
    unittest.main()
