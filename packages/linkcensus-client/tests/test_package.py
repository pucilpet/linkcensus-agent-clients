import importlib
from pathlib import Path
import tomllib
import unittest

from linkcensus_client import __version__


class PackageMetadataTests(unittest.TestCase):
    def test_distribution_entrypoint_and_dependency_metadata(self):
        root = Path(__file__).resolve().parents[1]
        metadata = tomllib.loads((root / "pyproject.toml").read_text())
        project = metadata["project"]
        self.assertEqual(project["name"], "linkcensus-client")
        self.assertEqual(project["version"], __version__)
        self.assertEqual(project["dependencies"], [])
        module, function = project["scripts"]["linkcensus"].split(":")
        self.assertTrue(callable(getattr(importlib.import_module(module), function)))
        self.assertTrue((root / "LICENSE").is_file())


if __name__ == "__main__":
    unittest.main()
