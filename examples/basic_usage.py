"""Basic usage example for screen-agent Python API."""

import asyncio

from screen_agent.capture import capture_screen
from screen_agent.input import keyboard_type, mouse_click, press_key
from screen_agent.window import focus_window, list_windows


async def main():
    # 1. Take a screenshot
    screenshot = await capture_screen()
    print(f"Screenshot: {screenshot['width']}x{screenshot['height']}px")
    print(f"Base64 length: {len(screenshot['image_base64'])} chars")

    # 2. List all open windows
    windows = await list_windows()
    for win in windows:
        print(f"  {win.get('app', '?')}: {win.get('title', '?')}")

    # 3. Focus a window and interact
    # await focus_window("Chrome")
    # await mouse_click(400, 300)
    # await keyboard_type("Hello from screen-agent!")
    # await press_key("enter")


if __name__ == "__main__":
    asyncio.run(main())
