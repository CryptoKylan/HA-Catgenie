"""Local write refusals, independent of entity and payload modules."""


class SettingsWriteRefused(Exception):
    """A local guard refused a settings write before any request was sent."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)
