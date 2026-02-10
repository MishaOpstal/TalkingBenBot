import json
import os
from typing import Dict

CONFIG_PATH = "data/config.json"

voice_enabled: Dict[int, bool] = {}


def load_config() -> None:
    global voice_enabled

    if not os.path.isfile(CONFIG_PATH):
        voice_enabled = {}
        return

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Keys come back as strings → convert to int
            voice_enabled = {int(k): bool(v) for k, v in data.items()}
    except Exception as e:
        print(f"[Config] Failed to load config: {e}")
        voice_enabled = {}


def save_config() -> None:
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(voice_enabled, f, indent=2)
    except Exception as e:
        print(f"[Config] Failed to save config: {e}")
