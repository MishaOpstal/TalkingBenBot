import json
import os
from typing import Dict

CONFIG_PATH = "data/config.json"

voice_enabled: Dict[int, bool] = {}

# Answer weights - these determine the relative probability of each answer type
# Higher number = more likely to be chosen
answer_weights = {
    "yes": 10,  # Weight for yes.mp3
    "no": 10,  # Weight for no.mp3
    "yapping": 2  # Weight for each yapping file
}


def load_config() -> None:
    global voice_enabled, answer_weights

    if not os.path.isfile(CONFIG_PATH):
        voice_enabled = {}
        return

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

            # Load voice_enabled (keys come back as strings → convert to int)
            if "voice_enabled" in data:
                voice_enabled = {int(k): bool(v) for k, v in data["voice_enabled"].items()}
            else:
                # Legacy format compatibility
                voice_enabled = {int(k): bool(v) for k, v in data.items() if k.isdigit()}

            # Load answer weights if present
            if "answer_weights" in data:
                answer_weights.update(data["answer_weights"])

    except Exception as e:
        print(f"[Config] Failed to load config: {e}")
        voice_enabled = {}


def save_config() -> None:
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)

        config_data = {
            "voice_enabled": voice_enabled,
            "answer_weights": answer_weights
        }

        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2)
    except Exception as e:
        print(f"[Config] Failed to save config: {e}")


def get_answer_weight(answer_type: str) -> int:
    """Get the weight for a specific answer type."""
    return answer_weights.get(answer_type, 1)


def set_answer_weight(answer_type: str, weight: int) -> None:
    """Set the weight for a specific answer type."""
    if weight < 0:
        weight = 0
    answer_weights[answer_type] = weight
    save_config()