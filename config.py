import os
import yaml
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.yaml"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {"server": {"host": "0.0.0.0", "port": 8888, "api_keys": []}, "providers": {}}
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_config(cfg: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


config = load_config()

# Override sensitive values from environment variables
if os.getenv("RELAY_API_KEYS"):
    config.setdefault("server", {})["api_keys"] = os.getenv("RELAY_API_KEYS").split(",")

if os.getenv("RELAY_PORT"):
    config.setdefault("server", {})["port"] = int(os.getenv("RELAY_PORT"))
