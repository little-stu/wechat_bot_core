"""配置加载：零第三方依赖，仅标准库 json。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_NAME = "config.json"
EXAMPLE_CONFIG_NAME = "config.example.json"


class ConfigError(Exception):
    pass


def _ensure_data_dir(cfg: dict[str, Any]) -> None:
    data_dir = PROJECT_ROOT / str(cfg.get("bot", {}).get("data_dir", "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    cfg.setdefault("bot", {})["data_dir_abs"] = str(data_dir)


def load_config(path: str | os.PathLike | None = None) -> dict[str, Any]:
    """加载配置文件。未指定时依次找 config.json / config.example.json。"""
    if path:
        cfg_path = Path(path)
    else:
        candidate = PROJECT_ROOT / DEFAULT_CONFIG_NAME
        if not candidate.exists():
            candidate = PROJECT_ROOT / EXAMPLE_CONFIG_NAME
        cfg_path = candidate

    if not cfg_path.exists():
        raise ConfigError(f"找不到配置文件: {cfg_path}")

    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg: dict[str, Any] = json.load(f)

    # 环境变量覆盖 API Key
    env_key = cfg.get("deepseek", {}).get("api_key_env", "DEEPSEEK_API_KEY")
    env_val = os.environ.get(env_key, "").strip()
    if env_val:
        cfg.setdefault("deepseek", {})["api_key"] = env_val

    _ensure_data_dir(cfg)
    return cfg


def get_source_groups(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return dict(cfg.get("worlds", {}).get("source", {}).get("groups", {}))


def get_hall(cfg: dict[str, Any]) -> dict[str, str]:
    return dict(cfg.get("worlds", {}).get("ops", {}).get("hall_group", {}))


def get_designers(cfg: dict[str, Any]) -> dict[str, dict[str, str]]:
    return dict(cfg.get("worlds", {}).get("ops", {}).get("designers", {}))


def get_dispatcher(cfg: dict[str, Any]) -> dict[str, str]:
    return dict(cfg.get("worlds", {}).get("ops", {}).get("dispatcher", {}))


def designer_name(cfg: dict[str, Any], contact_id: str) -> str:
    ds = get_designers(cfg)
    if contact_id in ds:
        return ds[contact_id].get("name", contact_id)
    return contact_id
