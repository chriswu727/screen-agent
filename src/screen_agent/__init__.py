"""Screen Agent - Give AI coding tools eyes and hands."""

__version__ = "0.1.0"

from screen_agent.capture import capture_screen, capture_region
from screen_agent.input import mouse_click, keyboard_type, press_key, scroll, drag
from screen_agent.server import create_server

__all__ = [
    "capture_screen",
    "capture_region",
    "mouse_click",
    "keyboard_type",
    "press_key",
    "scroll",
    "drag",
    "create_server",
]
