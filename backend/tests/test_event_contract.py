import json
import unittest
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "protocol" / "progressive-events.jsonl"


class EventContractTests(unittest.TestCase):
    def test_shared_jsonl_fixture_identities_and_forward_compatibility(self):
        lines = FIXTURE.read_text(encoding="utf-8").splitlines()
        events = [json.loads(line) for line in lines]
        self.assertEqual(len(events), 8)
        self.assertTrue(all(isinstance(event, dict) for event in events))
        by_type = {event["type"]: event for event in events}
        for event_type in ("title", "playlistEntry", "metadata", "inspectionError", "authWarning", "inspectionComplete"):
            event = by_type[event_type]
            self.assertEqual(event["requestId"], "r-1")
            self.assertEqual(event["generation"], 3)
            self.assertEqual(event["source"], "https://example.invalid/list")
        self.assertEqual(by_type["playlistEntry"]["itemId"], "item-a")
        self.assertEqual(by_type["playlistEntry"]["playlistPosition"], 0)
        self.assertEqual(by_type["metadata"]["itemId"], "item-a")
        self.assertEqual(by_type["progress"]["taskId"], "task-a")
        self.assertEqual(by_type["recordingFinalized"]["taskId"], "task-r")
        self.assertIn("index", by_type["inspectionError"])
        self.assertNotIn("itemId", by_type["inspectionError"])
        future = json.loads(lines[1])
        future["futureOptionalField"] = {"anything": True}
        decoded_future = json.loads(json.dumps(future))
        self.assertEqual(decoded_future["itemId"], "item-a")
        self.assertEqual(decoded_future["futureOptionalField"], {"anything": True})

    def test_malformed_json_is_rejected(self):
        with self.assertRaises(json.JSONDecodeError):
            json.loads('{"type":"playlistEntry",')


if __name__ == "__main__":
    unittest.main()
