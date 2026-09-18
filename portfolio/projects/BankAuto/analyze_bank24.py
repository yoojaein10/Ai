import pywinauto
from pywinauto import Desktop
import time
import os
import pyautogui

def analyze():
    print("--- 1. Checking Process List ---")
    os.system('tasklist /FI "IMAGENAME eq bank24.exe"')
    
    print("\n--- 2. Searching Windows (UIA backend) ---")
    try:
        desktop = Desktop(backend='uia')
        windows = desktop.windows()
        found = False
        for w in windows:
            title = w.window_text()
            if 'Bank' in title or 'bank' in title or 'Bank24' in title:
                print(f"Found Window: '{title}'")
                print(f"Class: {w.element_info.class_name}")
                print(f"Handle: {w.handle}")
                print(f"Rectangle: {w.rectangle()}")
                found = True
        if not found:
            print("No matching window found with 'Bank' in title.")
    except Exception as e:
        print(f"Error during window search: {e}")

    print("\n--- 3. Capturing Screen for UI Analysis ---")
    try:
        # Save a screenshot to the workspace to analyze the UI layout
        screenshot_path = "d:\\AI\\bank24_screen.png"
        pyautogui.screenshot(screenshot_path)
        print(f"Screenshot saved to: {screenshot_path}")
    except Exception as e:
        print(f"Error during screenshot: {e}")

if __name__ == "__main__":
    analyze()
