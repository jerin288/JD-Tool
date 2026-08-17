import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.services.settings_service import SettingsService


class SettingsTests(unittest.TestCase):
    def test_loads_defaults_and_persists_nested_updates(self) -> None:
        with TemporaryDirectory() as directory:
            settings_path = Path(directory) / "settings.json"
            service = SettingsService(settings_path)
            loaded = service.load()
            self.assertEqual(loaded["page_size"], 100)
            self.assertEqual(loaded["appearance_mode"], "Light")
            service.save({"appearance_mode": "Dark", "window": {"width": 1200}})
            stored = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(stored["appearance_mode"], "Dark")
            self.assertEqual(stored["window"]["width"], 1200)
            self.assertEqual(stored["window"]["height"], 900)


if __name__ == "__main__":
    unittest.main()
