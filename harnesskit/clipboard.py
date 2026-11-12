"""Clipboard helpers for CLI and GUI (no extra dependencies)."""

from __future__ import annotations

import os
import subprocess


def _qt_clipboard(text: str) -> bool:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return False
    app = QApplication.instance()
    if app is None:
        return False
    app.clipboard().setText(text)
    return True


def _windows_clipboard(text: str) -> bool:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.restype = wintypes.BOOL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]

    opened = False
    for _ in range(6):
        if user32.OpenClipboard(None):
            opened = True
            break
    if not opened:
        return False
    handle = None
    try:
        if not user32.EmptyClipboard():
            return False
        data = (text + "\0").encode("utf-16-le")
        handle = kernel32.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
        if not handle:
            return False
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return False
        try:
            ctypes.memmove(pointer, data, len(data))
        finally:
            kernel32.GlobalUnlock(handle)
        if not user32.SetClipboardData(13, handle):  # CF_UNICODETEXT
            return False
        handle = None  # ownership transferred to the clipboard
        return True
    finally:
        user32.CloseClipboard()
        if handle:
            kernel32.GlobalFree(handle)


def _tk_clipboard(text: str) -> None:
    import tkinter

    root = tkinter.Tk()
    try:
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
    finally:
        root.destroy()


def copy_text(text: str) -> str:
    """Copy text and return the mechanism used; raise RuntimeError on failure."""

    if _qt_clipboard(text):
        return "Qt"
    if os.name == "nt":
        try:
            if _windows_clipboard(text):
                return "Windows"
        except Exception:
            pass
    elif os.name == "posix":
        for command in (
            ["pbcopy"],
            ["wl-copy"],
            ["xclip", "-selection", "clipboard"],
            ["xsel", "--clipboard", "--input"],
        ):
            try:
                process = subprocess.run(command, input=text.encode("utf-8"), check=False)
                if process.returncode == 0:
                    return command[0]
            except OSError:
                continue
    try:
        _tk_clipboard(text)
        return "Tk"
    except Exception as error:  # pragma: no cover - environment specific
        raise RuntimeError(f"No se pudo escribir en el portapapeles: {error}") from error


# Compatibility with the original harness.
copy_to_clipboard = copy_text

__all__ = ["copy_text", "copy_to_clipboard"]
