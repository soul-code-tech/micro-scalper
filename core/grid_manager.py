import asyncio
import json
import os
from core.exchange import BingXAsync
from config import CONFIG

STATE_FILE = "state.json"

def load_state() -> dict:
    return json.load(open(STATE_FILE)) if os.path.exists(STATE_FILE) else {}

def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

class GridManager:
    def __init__(self, symbol: str, center)
