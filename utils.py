# utils.py
import random
import time


def random_delay(min_seconds=1, max_seconds=2) -> None:
    """Pause for a random duration to simulate human behavior."""
    time.sleep(random.uniform(min_seconds, max_seconds))
