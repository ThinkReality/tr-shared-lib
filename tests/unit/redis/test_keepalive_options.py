"""keepalive_options() must only name constants the running platform defines —
redis-py applies each one with setsockopt and closes the connection on any error."""

import socket

import pytest

from tr_shared.redis.connection import keepalive_options

LINUX = {"TCP_KEEPIDLE": 4, "TCP_KEEPINTVL": 5, "TCP_KEEPCNT": 6}


@pytest.fixture
def linux_socket(monkeypatch):
    for name, value in LINUX.items():
        monkeypatch.setattr(socket, name, value, raising=False)


@pytest.fixture
def macos_socket(monkeypatch):
    monkeypatch.delattr(socket, "TCP_KEEPIDLE", raising=False)
    monkeypatch.setattr(socket, "TCP_KEEPINTVL", 257, raising=False)
    monkeypatch.setattr(socket, "TCP_KEEPCNT", 258, raising=False)


def test_linux_gets_idle_interval_count(linux_socket):
    assert keepalive_options() == {4: 60, 5: 10, 6: 3}


def test_platform_without_keepidle_omits_it(macos_socket):
    assert keepalive_options() == {257: 10, 258: 3}


def test_platform_without_any_constant_yields_empty(monkeypatch):
    for name in LINUX:
        monkeypatch.delattr(socket, name, raising=False)
    assert keepalive_options() == {}
