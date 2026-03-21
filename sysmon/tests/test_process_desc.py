"""process_desc 영속화 기능 테스트."""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


class TestLoadProcessDesc:
    """_load_process_desc() 테스트."""

    def test_returns_dict(self):
        """반환값이 dict여야 한다."""
        from sysmon.collectors.base import _load_process_desc
        result = _load_process_desc()
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        """categories, by_name, by_cmd 키를 포함해야 한다."""
        from sysmon.collectors.base import _load_process_desc
        result = _load_process_desc()
        assert "categories" in result
        assert "by_name" in result
        assert "by_cmd" in result

    def test_categories_have_label_and_stop_desc(self):
        """각 카테고리에 label, stop_desc 필드가 있어야 한다."""
        from sysmon.collectors.base import _load_process_desc
        result = _load_process_desc()
        cats = result.get("categories", {})
        assert len(cats) > 0
        for key, val in cats.items():
            assert "label" in val, f"카테고리 '{key}'에 label 없음"
            assert "stop_desc" in val, f"카테고리 '{key}'에 stop_desc 없음"

    def test_loads_from_file(self, tmp_path):
        """JSON 파일이 있으면 그 내용을 로드해야 한다."""
        import sysmon.collectors.base as base_module

        custom = {
            "_meta": {"version": 1, "updated_at": "2026-01-01T00:00:00"},
            "categories": {"test_cat": {"label": "테스트", "stop_desc": "테스트 설명"}},
            "by_name": {},
            "by_cmd": {},
        }
        json_path = tmp_path / "process_desc.json"
        json_path.write_text(json.dumps(custom), encoding="utf-8")

        orig_path = base_module._PROCESS_DESC_PATH
        orig_cache = base_module._process_desc_cache
        orig_mtime = base_module._process_desc_mtime
        try:
            base_module._PROCESS_DESC_PATH = str(json_path)
            base_module._process_desc_cache = None
            base_module._process_desc_mtime = 0.0
            result = base_module._load_process_desc()
        finally:
            base_module._PROCESS_DESC_PATH = orig_path
            base_module._process_desc_cache = orig_cache
            base_module._process_desc_mtime = orig_mtime

        assert "test_cat" in result["categories"]

    def test_fallback_on_missing_file(self, tmp_path):
        """파일이 없으면 기본값을 반환해야 한다."""
        import sysmon.collectors.base as base_module

        missing_path = str(tmp_path / "nonexistent.json")
        orig_path = base_module._PROCESS_DESC_PATH
        orig_cache = base_module._process_desc_cache
        orig_mtime = base_module._process_desc_mtime
        try:
            base_module._PROCESS_DESC_PATH = missing_path
            base_module._process_desc_cache = None
            base_module._process_desc_mtime = 0.0
            result = base_module._load_process_desc()
        finally:
            base_module._PROCESS_DESC_PATH = orig_path
            base_module._process_desc_cache = orig_cache
            base_module._process_desc_mtime = orig_mtime

        assert isinstance(result, dict)
        assert "categories" in result

    def test_fallback_on_invalid_json(self, tmp_path):
        """JSON 파싱 오류 시 기본값을 반환해야 한다."""
        import sysmon.collectors.base as base_module

        bad_path = tmp_path / "bad.json"
        bad_path.write_text("NOT_VALID_JSON", encoding="utf-8")

        orig_path = base_module._PROCESS_DESC_PATH
        orig_cache = base_module._process_desc_cache
        orig_mtime = base_module._process_desc_mtime
        try:
            base_module._PROCESS_DESC_PATH = str(bad_path)
            base_module._process_desc_cache = None
            base_module._process_desc_mtime = 0.0
            result = base_module._load_process_desc()
        finally:
            base_module._PROCESS_DESC_PATH = orig_path
            base_module._process_desc_cache = orig_cache
            base_module._process_desc_mtime = orig_mtime

        assert isinstance(result, dict)
        assert "categories" in result


class TestSaveProcessDesc:
    """_save_process_desc() 테스트."""

    def test_saves_to_file(self, tmp_path):
        """데이터가 파일에 저장돼야 한다."""
        import sysmon.collectors.base as base_module

        json_path = tmp_path / "process_desc.json"
        data = {
            "_meta": {"version": 1, "updated_at": ""},
            "categories": {"test": {"label": "테스트", "stop_desc": "테스트"}},
            "by_name": {},
            "by_cmd": {},
        }

        orig_path = base_module._PROCESS_DESC_PATH
        orig_data_dir = base_module._DATA_DIR
        orig_cache = base_module._process_desc_cache
        orig_mtime = base_module._process_desc_mtime
        try:
            base_module._PROCESS_DESC_PATH = str(json_path)
            base_module._DATA_DIR = str(tmp_path)
            base_module._process_desc_cache = None
            base_module._process_desc_mtime = 0.0
            base_module._save_process_desc(data)
        finally:
            base_module._PROCESS_DESC_PATH = orig_path
            base_module._DATA_DIR = orig_data_dir
            base_module._process_desc_cache = orig_cache
            base_module._process_desc_mtime = orig_mtime

        assert json_path.exists()
        saved = json.loads(json_path.read_text(encoding="utf-8"))
        assert "test" in saved["categories"]

    def test_updates_meta_updated_at(self, tmp_path):
        """저장 시 _meta.updated_at이 갱신돼야 한다."""
        import sysmon.collectors.base as base_module

        json_path = tmp_path / "process_desc.json"
        data = {
            "_meta": {"version": 1, "updated_at": "1970-01-01T00:00:00"},
            "categories": {},
            "by_name": {},
            "by_cmd": {},
        }

        orig_path = base_module._PROCESS_DESC_PATH
        orig_data_dir = base_module._DATA_DIR
        orig_cache = base_module._process_desc_cache
        orig_mtime = base_module._process_desc_mtime
        try:
            base_module._PROCESS_DESC_PATH = str(json_path)
            base_module._DATA_DIR = str(tmp_path)
            base_module._process_desc_cache = None
            base_module._process_desc_mtime = 0.0
            base_module._save_process_desc(data)
        finally:
            base_module._PROCESS_DESC_PATH = orig_path
            base_module._DATA_DIR = orig_data_dir
            base_module._process_desc_cache = orig_cache
            base_module._process_desc_mtime = orig_mtime

        saved = json.loads(json_path.read_text(encoding="utf-8"))
        assert saved["_meta"]["updated_at"] != "1970-01-01T00:00:00"

    def test_creates_directory_if_missing(self, tmp_path):
        """디렉토리가 없어도 자동 생성해야 한다."""
        import sysmon.collectors.base as base_module

        nested_dir = tmp_path / "nested" / "dir"
        json_path = nested_dir / "process_desc.json"
        data = {"_meta": {"version": 1, "updated_at": ""}, "categories": {}, "by_name": {}, "by_cmd": {}}

        orig_path = base_module._PROCESS_DESC_PATH
        orig_data_dir = base_module._DATA_DIR
        orig_cache = base_module._process_desc_cache
        orig_mtime = base_module._process_desc_mtime
        try:
            base_module._PROCESS_DESC_PATH = str(json_path)
            base_module._DATA_DIR = str(nested_dir)
            base_module._process_desc_cache = None
            base_module._process_desc_mtime = 0.0
            base_module._save_process_desc(data)
        finally:
            base_module._PROCESS_DESC_PATH = orig_path
            base_module._DATA_DIR = orig_data_dir
            base_module._process_desc_cache = orig_cache
            base_module._process_desc_mtime = orig_mtime

        assert json_path.exists()


class TestLoadProcessDescCache:
    """_load_process_desc() 캐시/리로드 동작 테스트."""

    def test_cache_hit_no_reload(self, tmp_path):
        """파일 mtime이 같으면 캐시를 재사용해야 한다."""
        import sysmon.collectors.base as base_module

        custom = {
            "_meta": {"version": 1, "updated_at": "2026-01-01T00:00:00"},
            "categories": {"cache_cat": {"label": "캐시", "stop_desc": "캐시 테스트"}},
            "by_name": {},
            "by_cmd": {},
        }
        json_path = tmp_path / "process_desc.json"
        json_path.write_text(__import__("json").dumps(custom), encoding="utf-8")

        orig_path = base_module._PROCESS_DESC_PATH
        orig_cache = base_module._process_desc_cache
        orig_mtime = base_module._process_desc_mtime
        try:
            base_module._PROCESS_DESC_PATH = str(json_path)
            base_module._process_desc_cache = None
            base_module._process_desc_mtime = 0.0

            # 첫 번째 로드
            result1 = base_module._load_process_desc()
            # 두 번째 로드 (mtime 동일 — 캐시 hit)
            result2 = base_module._load_process_desc()
        finally:
            base_module._PROCESS_DESC_PATH = orig_path
            base_module._process_desc_cache = orig_cache
            base_module._process_desc_mtime = orig_mtime

        # 동일 객체를 반환해야 함 (캐시)
        assert result1 is result2

    def test_cache_invalidated_on_mtime_change(self, tmp_path):
        """파일이 변경되면(mtime 갱신) 리로드해야 한다."""
        import json
        import time
        import sysmon.collectors.base as base_module

        json_path = tmp_path / "process_desc.json"
        v1 = {
            "_meta": {"version": 1, "updated_at": ""},
            "categories": {"v1_cat": {"label": "V1", "stop_desc": "V1"}},
            "by_name": {},
            "by_cmd": {},
        }
        json_path.write_text(json.dumps(v1), encoding="utf-8")

        orig_path = base_module._PROCESS_DESC_PATH
        orig_cache = base_module._process_desc_cache
        orig_mtime = base_module._process_desc_mtime
        try:
            base_module._PROCESS_DESC_PATH = str(json_path)
            base_module._process_desc_cache = None
            base_module._process_desc_mtime = 0.0

            base_module._load_process_desc()

            # 파일 덮어쓰기 (mtime 변경 보장)
            time.sleep(0.01)
            v2 = {
                "_meta": {"version": 1, "updated_at": ""},
                "categories": {"v2_cat": {"label": "V2", "stop_desc": "V2"}},
                "by_name": {},
                "by_cmd": {},
            }
            json_path.write_text(json.dumps(v2), encoding="utf-8")

            result2 = base_module._load_process_desc()
        finally:
            base_module._PROCESS_DESC_PATH = orig_path
            base_module._process_desc_cache = orig_cache
            base_module._process_desc_mtime = orig_mtime

        assert "v2_cat" in result2["categories"]


class TestSaveAndLoadRoundTrip:
    """저장 후 즉시 로드 — 캐시 일관성 검증."""

    def test_save_updates_cache_immediately(self, tmp_path):
        """저장 직후 _load_process_desc()가 저장한 값을 반환해야 한다."""
        import json
        import sysmon.collectors.base as base_module

        json_path = tmp_path / "process_desc.json"
        data = {
            "_meta": {"version": 1, "updated_at": ""},
            "categories": {"roundtrip": {"label": "RT", "stop_desc": "RT"}},
            "by_name": {},
            "by_cmd": {},
        }

        orig_path = base_module._PROCESS_DESC_PATH
        orig_data_dir = base_module._DATA_DIR
        orig_cache = base_module._process_desc_cache
        orig_mtime = base_module._process_desc_mtime
        try:
            base_module._PROCESS_DESC_PATH = str(json_path)
            base_module._DATA_DIR = str(tmp_path)
            base_module._process_desc_cache = None
            base_module._process_desc_mtime = 0.0

            base_module._save_process_desc(data)
            loaded = base_module._load_process_desc()
        finally:
            base_module._PROCESS_DESC_PATH = orig_path
            base_module._DATA_DIR = orig_data_dir
            base_module._process_desc_cache = orig_cache
            base_module._process_desc_mtime = orig_mtime

        assert "roundtrip" in loaded["categories"]

    def test_save_without_meta_adds_meta(self, tmp_path):
        """_meta 키 없이 저장 시 자동으로 _meta가 추가돼야 한다."""
        import sysmon.collectors.base as base_module

        json_path = tmp_path / "process_desc.json"
        data_no_meta = {
            "categories": {"no_meta": {"label": "NM", "stop_desc": "NM"}},
            "by_name": {},
            "by_cmd": {},
        }

        orig_path = base_module._PROCESS_DESC_PATH
        orig_data_dir = base_module._DATA_DIR
        orig_cache = base_module._process_desc_cache
        orig_mtime = base_module._process_desc_mtime
        try:
            base_module._PROCESS_DESC_PATH = str(json_path)
            base_module._DATA_DIR = str(tmp_path)
            base_module._process_desc_cache = None
            base_module._process_desc_mtime = 0.0

            base_module._save_process_desc(data_no_meta)
        finally:
            base_module._PROCESS_DESC_PATH = orig_path
            base_module._DATA_DIR = orig_data_dir
            base_module._process_desc_cache = orig_cache
            base_module._process_desc_mtime = orig_mtime

        import json
        saved = json.loads(json_path.read_text(encoding="utf-8"))
        assert "_meta" in saved
        assert "updated_at" in saved["_meta"]


class TestProcessDescServerEdgeCases:
    """서버 /api/process-desc 경계값/에러 케이스 추가."""

    def test_post_empty_body_returns_400(self, server_no_token):
        """Content-Length=0 (빈 body) POST 시 400을 반환해야 한다."""
        from http.client import HTTPConnection
        host, port = server_no_token
        conn = HTTPConnection(host, port, timeout=5)
        conn.request(
            "POST", "/api/process-desc", body=b"",
            headers={"Content-Type": "application/json", "Content-Length": "0"},
        )
        resp = conn.getresponse()
        resp.read()
        conn.close()
        assert resp.status == 400

    def test_post_save_oserror_returns_500(self, server_no_token):
        """저장 경로를 읽기전용 디렉토리로 만들면 500을 반환해야 한다."""
        import os
        import sysmon.collectors.base as base_module
        from http.client import HTTPConnection
        host, port = server_no_token

        # 읽기전용 디렉토리 생성
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            ro_dir = os.path.join(tmp, "ro")
            os.makedirs(ro_dir)
            os.chmod(ro_dir, 0o444)  # 읽기전용

            orig_path = base_module._PROCESS_DESC_PATH
            orig_data_dir = base_module._DATA_DIR
            try:
                base_module._PROCESS_DESC_PATH = os.path.join(ro_dir, "process_desc.json")
                base_module._DATA_DIR = ro_dir

                payload_data = {
                    "_meta": {"version": 1, "updated_at": ""},
                    "categories": {},
                    "by_name": {},
                    "by_cmd": {},
                }
                import json
                payload = json.dumps(payload_data).encode()
                conn = HTTPConnection(host, port, timeout=5)
                conn.request(
                    "POST", "/api/process-desc", body=payload,
                    headers={"Content-Type": "application/json", "Content-Length": str(len(payload))},
                )
                resp = conn.getresponse()
                resp.read()
                conn.close()
                status = resp.status
            finally:
                os.chmod(ro_dir, 0o755)  # 정리를 위해 권한 복구
                base_module._PROCESS_DESC_PATH = orig_path
                base_module._DATA_DIR = orig_data_dir

        assert status == 500


class TestBuildDefaultProcessDesc:
    """_build_default_process_desc() 테스트."""

    def test_has_standard_categories(self):
        """표준 카테고리가 모두 포함돼야 한다."""
        from sysmon.collectors.base import _build_default_process_desc
        result = _build_default_process_desc()
        cats = result["categories"]
        for expected in ("security", "chrome", "docker", "warp", "ide", "system", "kakaotalk", "other"):
            assert expected in cats, f"카테고리 '{expected}' 없음"

    def test_has_by_name_entries(self):
        """by_name 항목이 존재해야 한다."""
        from sysmon.collectors.base import _build_default_process_desc
        result = _build_default_process_desc()
        assert len(result["by_name"]) > 0

    def test_has_by_cmd_entries(self):
        """by_cmd 항목이 존재해야 한다."""
        from sysmon.collectors.base import _build_default_process_desc
        result = _build_default_process_desc()
        assert len(result["by_cmd"]) > 0


class TestCollectAllIncludesProcessDesc:
    """collect_all()에 process_desc가 포함되는지 테스트."""

    def test_collect_all_has_process_desc_key(self):
        """collect_all() 반환값에 process_desc 키가 있어야 한다."""
        from sysmon.collectors import get_collector
        collector = get_collector()
        result = collector.collect_all()
        assert "process_desc" in result

    def test_process_desc_in_collect_all_has_categories(self):
        """collect_all()의 process_desc에 categories가 있어야 한다."""
        from sysmon.collectors import get_collector
        collector = get_collector()
        result = collector.collect_all()
        pd = result["process_desc"]
        assert "categories" in pd


class TestProcessDescServerEndpoint:
    """서버 /api/process-desc 엔드포인트 테스트."""

    def test_get_process_desc(self, server_no_token):
        """GET /api/process-desc 가 JSON을 반환해야 한다."""
        from http.client import HTTPConnection
        host, port = server_no_token
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/api/process-desc")
        resp = conn.getresponse()
        body = resp.read()
        conn.close()

        assert resp.status == 200
        data = json.loads(body)
        assert "categories" in data

    def test_post_process_desc(self, server_no_token):
        """POST /api/process-desc 로 저장 후 GET에서 반영돼야 한다 (원복 포함)."""
        import sysmon.collectors.base as base_module
        from http.client import HTTPConnection
        host, port = server_no_token

        # 현재 데이터 로드
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/api/process-desc")
        resp = conn.getresponse()
        original = json.loads(resp.read())
        conn.close()

        # 수정하여 저장
        modified = json.loads(json.dumps(original))
        modified.setdefault("categories", {})
        modified["categories"]["_test_cat"] = {"label": "테스트라벨", "stop_desc": "테스트설명"}

        payload = json.dumps(modified).encode()
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("POST", "/api/process-desc", body=payload,
                     headers={"Content-Type": "application/json", "Content-Length": str(len(payload))})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        assert resp.status == 200

        # 다시 GET으로 확인
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("GET", "/api/process-desc")
        resp = conn.getresponse()
        after = json.loads(resp.read())
        conn.close()
        assert "_test_cat" in after.get("categories", {})

        # 원복: _test_cat 제거하여 다시 저장
        original.get("categories", {}).pop("_test_cat", None)
        restore_payload = json.dumps(original).encode()
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("POST", "/api/process-desc", body=restore_payload,
                     headers={"Content-Type": "application/json", "Content-Length": str(len(restore_payload))})
        resp = conn.getresponse()
        resp.read()
        conn.close()

    def test_post_invalid_json_returns_400(self, server_no_token):
        """잘못된 JSON POST 시 400을 반환해야 한다."""
        from http.client import HTTPConnection
        host, port = server_no_token
        payload = b"NOT_JSON"
        conn = HTTPConnection(host, port, timeout=5)
        conn.request("POST", "/api/process-desc", body=payload,
                     headers={"Content-Type": "application/json", "Content-Length": str(len(payload))})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        assert resp.status == 400


# server_no_token fixture 재사용 (test_server.py와 동일 방식)
import socket
from threading import Thread
import time


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(host: str, port: int, timeout: float = 5.0) -> None:
    from http.client import HTTPConnection
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            conn = HTTPConnection(host, port, timeout=1)
            conn.request("GET", "/")
            conn.getresponse()
            conn.close()
            return
        except (ConnectionRefusedError, OSError):
            time.sleep(0.1)
    raise TimeoutError(f"서버가 {timeout}초 내에 시작되지 않음")


@pytest.fixture(scope="module")
def server_no_token():
    from sysmon.server import serve
    port = _find_free_port()
    host = "127.0.0.1"
    thread = Thread(
        target=serve,
        kwargs={"host": host, "port": port, "token": None, "open_browser": False},
        daemon=True,
    )
    thread.start()
    _wait_for_server(host, port)
    yield host, port
