import hashlib
import json
import os
import re
from typing import Any

from helpers.audio_helper import AUDIO_PATH

SOUND_INVENTORY_PATH = "data/sound_inventory.json"


def _extract_message_from_filename(filepath: str) -> str:
    """Extract the Discord message shown for a sound file."""
    filename = os.path.basename(filepath)
    match = re.search(r"\[(.*?)\]", filename)
    if match:
        return match.group(1)

    name_without_ext = os.path.splitext(filename)[0]
    return name_without_ext.capitalize()


def _hash_file(filepath: str) -> str:
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()


def _load_inventory() -> dict[str, Any]:
    if not os.path.isfile(SOUND_INVENTORY_PATH):
        return {"sounds": []}

    try:
        with open(SOUND_INVENTORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"sounds": []}

    if not isinstance(data, dict):
        return {"sounds": []}

    sounds = data.get("sounds")
    if not isinstance(sounds, list):
        data["sounds"] = []

    return data


def refresh_sound_inventory() -> None:
    """
    Rebuild/refresh sound inventory on startup.

    - Never deletes historical entries.
    - Marks missing entries as isPresent=False.
    - If a file moved/renamed but has the same hash, updates the stored path.
    """
    os.makedirs(os.path.dirname(SOUND_INVENTORY_PATH), exist_ok=True)

    data = _load_inventory()
    sounds: list[dict[str, Any]] = data.setdefault("sounds", [])

    existing_by_hash: dict[str, dict[str, Any]] = {}
    for entry in sounds:
        if not isinstance(entry, dict):
            continue

        file_hash = entry.get("hash")
        if isinstance(file_hash, str) and file_hash and file_hash not in existing_by_hash:
            existing_by_hash[file_hash] = entry

    discovered_files: list[str] = []
    if os.path.isdir(AUDIO_PATH):
        for root, _, files in os.walk(AUDIO_PATH):
            for file in files:
                if file.lower().endswith(".mp3"):
                    discovered_files.append(os.path.abspath(os.path.join(root, file)))

    seen_hashes: set[str] = set()
    for file_path in discovered_files:
        try:
            file_hash = _hash_file(file_path)
        except OSError:
            continue

        seen_hashes.add(file_hash)
        message = _extract_message_from_filename(file_path)

        existing_entry = existing_by_hash.get(file_hash)
        if existing_entry:
            existing_entry["absolutePath"] = file_path
            # Keep existing discordMessage for hash matches (rename/move safety).
            existing_entry["isPresent"] = True
            continue

        new_entry = {
            "absolutePath": file_path,
            "discordMessage": message,
            "hash": file_hash,
            "isPresent": True,
        }
        sounds.append(new_entry)
        existing_by_hash[file_hash] = new_entry

    for entry in sounds:
        if not isinstance(entry, dict):
            continue

        file_hash = entry.get("hash")
        if isinstance(file_hash, str) and file_hash:
            entry["isPresent"] = file_hash in seen_hashes

    with open(SOUND_INVENTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_message_for_sound(file_path: str) -> str:
    """Get the Discord message for a sound path from inventory, with fallback extraction."""
    if not file_path:
        return "..."

    normalized_path = os.path.abspath(file_path)
    data = _load_inventory()
    sounds = data.get("sounds", [])

    if isinstance(sounds, list):
        for entry in sounds:
            if not isinstance(entry, dict):
                continue

            path_in_inventory = entry.get("absolutePath")
            if isinstance(path_in_inventory, str) and os.path.abspath(path_in_inventory) == normalized_path:
                message = entry.get("discordMessage")
                if isinstance(message, str) and message:
                    return message

    return _extract_message_from_filename(file_path)