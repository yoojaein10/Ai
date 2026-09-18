import pywinauto
from pywinauto import Desktop
import time
import os

def analyze_all_windows():
    print("--- 1. Listing ALL Top-level Windows (UIA) ---")
    try:
        desktop = Desktop(backend='uia')
        windows = desktop.windows()
        for w in windows:
            title = w.window_text()
            if title.strip(): # Only print windows with titles
                print(f"Title: '{title}', Class: {w.element_info.class_name}, Rect: {w.rectangle()}")
    except Exception as e:
        print(f"UIA Error: {e}")

    print("\n--- 2. Listing ALL Top-level Windows (Win32) ---")
    try:
        desktop_win32 = Desktop(backend='win32')
        windows_win32 = desktop_win32.windows()
        for w in windows_win32:
            title = w.window_text()
            if title.strip():
                print(f"Title: '{title}', Class: {w.element_info.class_name}, Rect: {w.rectangle()}")
    except Exception as e:
        print(f"Win32 Error: {e}")

if __name__ == "__main__":
    analyze_all_windows()
