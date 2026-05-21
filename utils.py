# utils.py
import time
import random

def random_delay(min_seconds=1, max_seconds=2):
    """Pauses the bot for a random amount of time to simulate human behavior."""
    delay = random.uniform(min_seconds, max_seconds)
    print(f"[*] Sleeping for {delay:.2f} seconds...")
    time.sleep(delay)