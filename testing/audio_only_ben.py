import os
import random
import time
import keyboard
import pygame

pygame.mixer.init()

BASE_PATH = "../assets/sounds"

CALL_PATH = os.path.join(BASE_PATH, "telephone", "call")
HANG_UP_PATH = os.path.join(BASE_PATH, "telephone", "hang_up")
ANSWER_PATH = os.path.join(BASE_PATH, "answers")
YAPPING_PATH = os.path.join(BASE_PATH, "yapping")

on_call = False


def get_audio_files(path):
    if not os.path.isdir(path):
        return []

    return [
        os.path.join(path, f)
        for f in os.listdir(path)
        if f.lower().endswith(".mp3")
    ]


def play_sound(file_path, delay: float = 0.025):
    if not file_path or not os.path.isfile(file_path):
        return

    pygame.mixer.music.load(file_path)
    pygame.mixer.music.play()

    while pygame.mixer.music.get_busy():
        time.sleep(delay)


def play_sequence(path):
    files = get_audio_files(path)
    for file in files:
        play_sound(file, delay=.7)


def play_random(path):
    files = get_audio_files(path)
    if not files:
        return

    play_sound(random.choice(files))


def talk_to_ben():
    yes = os.path.join(ANSWER_PATH, "yes.mp3")
    no = os.path.join(ANSWER_PATH, "no.mp3")
    yaps = get_audio_files(YAPPING_PATH)

    weighted_pool = []

    if os.path.isfile(yes):
        weighted_pool.extend([yes] * 6)

    if os.path.isfile(no):
        weighted_pool.extend([no] * 6)

    weighted_pool.extend(yaps * 2)

    if not weighted_pool:
        return

    play_sound(random.choice(weighted_pool))


def toggle_call():
    global on_call

    if not on_call:
        print("Calling Ben...")
        play_sequence(CALL_PATH)
        on_call = True
    else:
        print("Hanging up...")
        play_random(HANG_UP_PATH)
        on_call = False


def main():
    print("Talking Ben (audio-only)")
    print("------------------------")

    call_key = input("Set CALL / HANG UP hotkey: ").strip()
    talk_key = input("Set TALK hotkey: ").strip()

    keyboard.add_hotkey(call_key, toggle_call)

    keyboard.add_hotkey(
        talk_key,
        lambda: talk_to_ben() if on_call else None
    )

    print("\nReady.")
    print("Press ESC to quit.")

    keyboard.wait("esc")


if __name__ == "__main__":
    main()
