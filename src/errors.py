class ConfigError(Exception):
    """The configuration file is missing or invalid."""


class EmulatorError(Exception):
    """The ammeter emulators could not be started."""


class ArchiveError(Exception):
    """A run is missing from the results archive, or its files are damaged."""


class AmmeterError(Exception):
    """A measurement could not be read from an ammeter."""


class AmmeterConnectionError(AmmeterError):
    pass


class AmmeterTimeoutError(AmmeterError):
    pass


class AmmeterResponseError(AmmeterError):
    """The ammeter answered, but not with a valid reading."""
