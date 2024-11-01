from typing import TypeVar

T = TypeVar("T", bound=object)

def export_values(cls: T) -> T:
    setattr(cls, "_EXPORT_VALUES", True)
    return cls
