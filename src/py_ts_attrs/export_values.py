from typing import Type, TypeVar

T = TypeVar("T", bound=Type)

def export_values(cls: T) -> T:
    cls._EXPORT_VALUES = True
    return cls
