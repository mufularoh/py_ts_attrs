import enum
import typing

ET = typing.TypeVar("ET", bound=enum.Enum)
def parse_enum(enum_cls: typing.Type[ET], value: str) -> typing.Optional[ET]:
    allowed_values = {v.value: v for v in enum_cls._member_map_.values()}
    if value and value in allowed_values and allowed_values[value]:
        return allowed_values[value]  # type: ignore
    return None

