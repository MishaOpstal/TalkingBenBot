import os

ASSET_PATH = "/app/assets"
AUDIO_PATH = os.path.join(ASSET_PATH, "sounds")
MOVIE_PATH = os.path.join(ASSET_PATH, "movies")

CALL_PATH = os.path.join(AUDIO_PATH, "telephone", "call")
HANG_UP_PATH = os.path.join(AUDIO_PATH, "telephone", "hang_up")
ANSWER_PATH = os.path.join(AUDIO_PATH, "answers")
YAPPING_PATH = os.path.join(AUDIO_PATH, "yapping")

def get_audio_files(path: str) -> list[str]:
    if not os.path.isdir(path):
        return []

    return [
        os.path.join(path, f)
        for f in os.listdir(path)
        if f.lower().endswith(".mp3")
    ]

def get_associated_video(audio_path: str):
    if not os.path.isfile(audio_path):
        return None

    # Look for mp4 with same name in /app/assets/movies
    base_name = os.path.basename(audio_path)
    relative_path = audio_path.replace("/app/assets/sounds/", "")
    video_name = base_name.replace(".mp3", ".mp4")
    video_path = os.path.join(MOVIE_PATH, relative_path, video_name)
    if os.path.isfile(video_path):
        return video_path

    # If the path includes call we know it is the scripted phone pickup, play pickup.mp4
    if "call" in relative_path:
        return os.path.join(MOVIE_PATH, relative_path, "pickup.mp4")

    # If the path includes hang_up we know it is the scripted phone hangup, play hangup.mp4
    if "hang_up" in relative_path:
        return os.path.join(MOVIE_PATH, relative_path, "hangup.mp4")

    return None