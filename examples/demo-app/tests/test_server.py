from demo_app.server import PORT


def test_port_is_unprivileged() -> None:
    assert PORT > 1024
