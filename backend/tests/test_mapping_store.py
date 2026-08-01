import os
import sys
import unittest

# PATH FIX
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src import mapping_store

# These are integration tests against a real Postgres database — they need
# DATABASE_URL pointing at one (e.g. a local Postgres or a Neon dev branch).
# Skipped automatically when it isn't set, so the rest of the suite (which
# needs no database) still runs anywhere.
requires_database = unittest.skipUnless(
    os.environ.get("DATABASE_URL"), "DATABASE_URL not set — skipping mapping_store integration tests"
)


@requires_database
class TestMappingStore(unittest.TestCase):

    def setUp(self):
        self.test_names = []

    def tearDown(self):
        for name in self.test_names:
            mapping_store.delete_mapping(name)

    def _tracked_name(self, name):
        self.test_names.append(name)
        return name

    def test_save_and_get_roundtrip(self):
        name = self._tracked_name("test_roundtrip")
        config = {"field_mappings": {"customer_id": {"sheet": "S", "column": "C"}}}

        mapping_store.save_mapping(name, config)
        self.assertEqual(mapping_store.get_mapping(name), config)

    def test_save_overwrites_existing(self):
        name = self._tracked_name("test_overwrite")
        mapping_store.save_mapping(name, {"a": 1})
        mapping_store.save_mapping(name, {"a": 2})
        self.assertEqual(mapping_store.get_mapping(name), {"a": 2})

    def test_get_missing_mapping_returns_none(self):
        self.assertIsNone(mapping_store.get_mapping("does_not_exist_at_all"))

    def test_list_includes_saved_name(self):
        name = self._tracked_name("test_list_me")
        mapping_store.save_mapping(name, {"a": 1})
        self.assertIn(name, mapping_store.list_mapping_names())

    def test_delete_removes_mapping(self):
        name = self._tracked_name("test_delete_me")
        mapping_store.save_mapping(name, {"a": 1})
        self.assertTrue(mapping_store.delete_mapping(name))
        self.assertIsNone(mapping_store.get_mapping(name))

    def test_delete_missing_mapping_returns_false(self):
        self.assertFalse(mapping_store.delete_mapping("never_existed_here"))

    def test_delete_all_except_protected(self):
        keep = self._tracked_name("electra_default")
        drop = self._tracked_name("test_drop_me")
        mapping_store.save_mapping(drop, {"a": 1})

        mapping_store.delete_all_mappings(except_name=keep)

        self.assertIsNone(mapping_store.get_mapping(drop))
        self.assertIsNotNone(mapping_store.get_mapping(keep))  # seeded bundled default

    def test_bundled_default_mapping_is_seeded(self):
        # Any call triggers the one-time schema/seed check.
        mapping_store.list_mapping_names()
        self.assertIsNotNone(mapping_store.get_mapping("electra_default"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
