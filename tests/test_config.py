from pathlib import Path

import pytest

from tether.config import Config, ConfigError, find_root, load_config


def write_pyproject(root: Path, body: str) -> None:
    (root / "pyproject.toml").write_text(body)


def test_defaults_without_pyproject(tmp_path: Path) -> None:
    assert load_config(tmp_path) == Config(root=tmp_path)


def test_reads_tether_table(tmp_path: Path) -> None:
    write_pyproject(
        tmp_path,
        '[tool.tether]\ntest_dirs = ["spec"]\nmax_stop_attempts = 5\n',
    )

    config = load_config(tmp_path)

    assert config.test_dirs == ("spec",)
    assert config.max_stop_attempts == 5


def test_rejects_unknown_keys(tmp_path: Path) -> None:
    write_pyproject(tmp_path, "[tool.tether]\ntypo_key = 1\n")

    with pytest.raises(ConfigError, match="typo_key"):
        load_config(tmp_path)


def test_rejects_bad_selection(tmp_path: Path) -> None:
    write_pyproject(tmp_path, '[tool.tether]\nselection = "magic"\n')

    with pytest.raises(ConfigError, match="selection"):
        load_config(tmp_path)


def test_find_root_walks_up_to_pyproject(tmp_path: Path) -> None:
    write_pyproject(tmp_path, "")
    nested = tmp_path / "src" / "pkg"
    nested.mkdir(parents=True)

    assert find_root(nested) == tmp_path.resolve()


def test_reads_slot_env_table(tmp_path: Path) -> None:
    write_pyproject(
        tmp_path,
        "[tool.tether.slot_env]\n"
        'PORT = "{8000 + slot}"\n'
        'DATABASE_URL = "sqlite:///app_{slot}.db"\n',
    )

    config = load_config(tmp_path)

    assert config.slot_env == {
        "PORT": "{8000 + slot}",
        "DATABASE_URL": "sqlite:///app_{slot}.db",
    }


def test_rejects_non_table_slot_env(tmp_path: Path) -> None:
    write_pyproject(tmp_path, '[tool.tether]\nslot_env = "PORT"\n')

    with pytest.raises(ConfigError, match="slot_env"):
        load_config(tmp_path)
