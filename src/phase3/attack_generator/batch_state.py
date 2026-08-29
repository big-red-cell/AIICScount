import json
from pathlib import Path
from typing import Any


class BatchItemError(Exception):
    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


class BatchRunStore:
    def __init__(self, *, results_path: Path, status_path: Path):
        self.results_path = results_path
        self.status_path = status_path
        self.results = self._load_json_object(results_path)
        self.status = self._load_json_object(status_path)

    def pending_items(self, items: list[object]) -> list[object]:
        return [item for item in items if self.should_process(item)]

    def should_process(self, item: object) -> bool:
        key = str(item)
        if key not in self.results:
            return True

        status_entry = self.status.get(key)
        if not isinstance(status_entry, dict):
            return False
        return status_entry.get("status") != "success"

    def record_success(self, item: object, result: Any) -> None:
        key = str(item)
        self.results[key] = result
        self.status[key] = {"status": "success"}
        self.save()

    def record_error(self, item: object, *, stage: str, error: str, clear_result: bool = True) -> None:
        key = str(item)
        if clear_result:
            self.results.pop(key, None)
        self.status[key] = {
            "status": "error",
            "stage": stage,
            "error": error,
        }
        self.save()

    def save(self) -> None:
        self.results_path.parent.mkdir(parents=True, exist_ok=True)
        self.status_path.parent.mkdir(parents=True, exist_ok=True)

        with self.results_path.open("w", encoding="utf-8") as f:
            json.dump(self.results, f, indent=4, ensure_ascii=False)

        with self.status_path.open("w", encoding="utf-8") as f:
            json.dump(self.status, f, indent=4, ensure_ascii=False)

    @staticmethod
    def _load_json_object(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}

        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError(f"{path} must contain a JSON object.")

        return data
