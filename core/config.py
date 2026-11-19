"""Configuration manager for Deal Scout."""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any, Dict
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

CONFIG_YAML_PATH = ROOT / "config.yaml"


def load_config() -> Dict[str, Any]:
    """Load configuration from config.yaml."""
    if CONFIG_YAML_PATH.exists():
        try:
            with open(CONFIG_YAML_PATH, "r") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"[config] Warning loading config.yaml: {e}")
    return {}


def save_config_yaml(cfg: Dict[str, Any]) -> None:
    with open(CONFIG_YAML_PATH, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
