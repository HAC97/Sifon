import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from app.errors import DownloadFailure, ErrorCode
from app.jobs import JobManager
from app.main import contract, create_app

CONTRACT_PATH = Path(__file__).resolve().parents[3] / "contracts" / "api.openapi.json"


def validate(instance, schema_name):
    doc = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    schema = {"$ref": f"#/components/schemas/{schema_name}", "components": doc["components"]}
    Draft202012Validator(schema).validate(instance)


def test_committed_contract_matches_the_code():
    committed = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert committed == contract(), "run: python scripts/gen_contract.py"


@pytest.fixture
def client(tmp_path):
    def runner(job, on_progress):
        if job.mode == "audio":
            raise DownloadFailure(ErrorCode.NETWORK)
        path = job.dir / "a.mp4"
        path.write_bytes(b"x")
        return path

    manager = JobManager(tmp_path / "jobs", runner)
    app = create_app(
        manager=manager,
        info_fetcher=lambda url: {"title": "T", "thumbnail": None, "duration": 1, "uploader": None, "heights": [720]},
        url_validator=lambda u: u,
        serve_web=False,
    )
    yield TestClient(app)
    manager.shutdown()


def wait_finished(client, job_id):
    import time

    for _ in range(300):
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] in ("done", "error"):
            return body
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_responses_validate_against_committed_schemas(client):
    validate(client.get("/api/health").json(), "HealthResponse")
    validate(client.post("/api/info", json={"url": "https://example.com/v"}).json(), "InfoResponse")

    created = client.post("/api/jobs", json={"url": "https://example.com/v", "mode": "video"})
    validate(created.json(), "JobCreated")
    validate(wait_finished(client, created.json()["job_id"]), "JobStatus")

    failed = client.post("/api/jobs", json={"url": "https://example.com/v", "mode": "audio"})
    validate(wait_finished(client, failed.json()["job_id"]), "JobStatus")


def test_error_body_validates_against_committed_schema(tmp_path):
    def failing(url):
        raise DownloadFailure(ErrorCode.UNSUPPORTED_SITE)

    manager = JobManager(tmp_path / "jobs", lambda job, cb: job.dir)
    app = create_app(manager=manager, info_fetcher=failing, url_validator=lambda u: u, serve_web=False)
    res = TestClient(app).post("/api/info", json={"url": "https://example.com/v"})
    assert res.status_code == 400
    validate(res.json(), "ErrorBody")
    manager.shutdown()
