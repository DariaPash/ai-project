"""Stable errors: never interpolate untrusted content into diagnostic messages."""


class CoreError(Exception):
    def __init__(self, code, reason, exit_code=2, *, saved=None, next_action="Correct the input and retry", data=None):
        super().__init__(reason)
        self.code = code
        self.reason = reason
        self.exit_code = exit_code
        self.saved = saved
        self.next_action = next_action
        self.data = data
