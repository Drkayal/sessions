"""
Minimal imghdr compatibility shim for Python 3.13+ environments
that still expect the standard library 'imghdr' module.

This module provides a stub 'what' function used by older versions
of python-telegram-bot to guess image types. Returning None by default
is sufficient for bots that do not rely on automatic image type detection.
"""

from typing import Optional, Union


def what(file: Union[str, bytes, "os.PathLike"], h: Optional[bytes] = None) -> Optional[str]:

    return None

