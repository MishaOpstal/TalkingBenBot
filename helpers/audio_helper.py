import os

BASE_PATH = "assets/sounds"

CALL_PATH = os.path.join(BASE_PATH, "telephone", "call")
HANG_UP_PATH = os.path.join(BASE_PATH, "telephone", "hang_up")
ANSWER_PATH = os.path.join(BASE_PATH, "answers")
YAPPING_PATH = os.path.join(BASE_PATH, "yapping")

def get_audio_files(path: str) -> list[str]:
    if not os.path.isdir(path):
        return []

    return [
        os.path.join(path, f)
        for f in os.listdir(path)
        if f.lower().endswith(".mp3")
    ]
