"""Shared diagnostic escaping so that every printed problem is exactly one line.

A problem string can carry user data: a JSON key or string value decoded from
a file, a file name, or the text of a parser exception that quotes either.
Those may hold a line break or another control character. printable() turns
each control character into a visible escape so that one diagnostic is one
output line.
"""

import argparse
import re
import sys

CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_NAMED_ESCAPES = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _escape_control(match):
    char = match.group(0)
    return _NAMED_ESCAPES.get(char) or "\\x%02x" % ord(char)


def printable(text):
    """Return TEXT with control characters backslash-escaped, so one diagnostic is one line."""
    return CONTROL.sub(_escape_control, str(text))


class SingleLineParser(argparse.ArgumentParser):
    """ArgumentParser whose error line is escaped with printable(), so a user-supplied
    argument cannot break the one-line diagnostic convention. Usage text is static."""

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, "%s: error: %s\n" % (self.prog, printable(message)))
