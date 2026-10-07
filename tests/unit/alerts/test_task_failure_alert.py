import json
import uuid

import httpx
import pytest

from tr_shared.alerts import slack
from tr_shared.alerts.slack import TASK_ALERTS_PER_HOUR, alert_task_failed_permanently

WEBHOOK = "https://hooks.slack.com/services/test"


@pytest.fixture
def slack_posts(monkeypatch):
    posts: list[dict] = []

    def record(request: httpx.Request) -> httpx.Response:
        posts.append(json.loads(request.content))
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(record))
    monkeypatch.setattr(slack, "_sync_client", client)
    yield posts
    client.close()


def _alert(task_name: str, webhook_url: str = WEBHOOK) -> None:
    alert_task_failed_permanently(
        webhook_url=webhook_url,
        service="lead-management",
        environment="staging",
        task_name=task_name,
        task_id="task-123",
        correlation_id="corr-456",
        error_type="DatabaseUnavailableError",
    )


def test_a_permanent_failure_posts_one_alert_naming_the_task(slack_posts):
    task_name = f"lead.process_webhook.{uuid.uuid4().hex}"

    _alert(task_name)

    assert len(slack_posts) == 1
    text = json.dumps(slack_posts[0])
    for expected in (task_name, "task-123", "corr-456", "DatabaseUnavailableError", "staging"):
        assert expected in text
    assert (
        slack_posts[0]["blocks"][0]["text"]["text"] == "lead-management — task failed permanently"
    )


def test_one_task_pages_at_most_the_hourly_budget(slack_posts):
    task_name = f"lead.noisy.{uuid.uuid4().hex}"

    for _ in range(TASK_ALERTS_PER_HOUR + 3):
        _alert(task_name)

    assert len(slack_posts) == TASK_ALERTS_PER_HOUR


def test_a_noisy_task_does_not_mute_another_task(slack_posts):
    noisy = f"lead.noisy.{uuid.uuid4().hex}"
    for _ in range(TASK_ALERTS_PER_HOUR + 1):
        _alert(noisy)

    _alert(f"lead.quiet.{uuid.uuid4().hex}")

    assert len(slack_posts) == TASK_ALERTS_PER_HOUR + 1


def test_no_webhook_posts_nothing(slack_posts):
    _alert(f"lead.task.{uuid.uuid4().hex}", webhook_url="")

    assert slack_posts == []


@pytest.mark.parametrize(
    "answer",
    [
        lambda request: httpx.Response(500),
        lambda request: (_ for _ in ()).throw(httpx.ConnectError("down")),
    ],
    ids=["slack-500", "slack-unreachable"],
)
def test_a_failing_webhook_never_raises_into_the_task(monkeypatch, answer):
    client = httpx.Client(transport=httpx.MockTransport(answer))
    monkeypatch.setattr(slack, "_sync_client", client)

    _alert(f"lead.task.{uuid.uuid4().hex}")

    client.close()
