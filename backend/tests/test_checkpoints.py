from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from backend.app.core import JsonCheckpointStore


class CheckpointStoreTests(unittest.TestCase):
    def test_json_checkpoint_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state.json"
            store = JsonCheckpointStore(path)
            payload = {"next_index": 42, "completed": False}

            store.write(payload)
            restored = store.read()

            self.assertEqual(payload, restored)


if __name__ == "__main__":
    unittest.main()

