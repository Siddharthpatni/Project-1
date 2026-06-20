from pathlib import Path
import shutil
import unittest
import uuid

from tender_agent.input_loader import load_urls


class InputLoaderTests(unittest.TestCase):
    def _workspace_temp_dir(self) -> Path:
        root = Path.cwd() / ".tmp_test_workspace"
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"case_{uuid.uuid4().hex}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def test_loads_urls_from_csv_and_applies_limit(self) -> None:
        temp_dir = self._workspace_temp_dir()
        try:
            csv_path = temp_dir / "urls.csv"
            csv_path.write_text(
                "tender_url,name\n"
                "https://example.com/1,One\n"
                "https://example.com/2,Two\n"
                "https://example.com/3,Three\n",
                encoding="utf-8",
            )

            urls = load_urls(
                direct_urls=[],
                csv_path=csv_path,
                csv_column="tender_url",
                limit=2,
            )

            self.assertEqual(
                urls,
                ["https://example.com/1", "https://example.com/2"],
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_deduplicates_direct_and_csv_urls(self) -> None:
        temp_dir = self._workspace_temp_dir()
        try:
            csv_path = temp_dir / "urls.csv"
            csv_path.write_text(
                "url\nhttps://example.com/1\nhttps://example.com/2\n",
                encoding="utf-8",
            )

            urls = load_urls(
                direct_urls=["https://example.com/1", "https://example.com/3"],
                csv_path=csv_path,
            )

            self.assertEqual(
                urls,
                [
                    "https://example.com/1",
                    "https://example.com/3",
                    "https://example.com/2",
                ],
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
