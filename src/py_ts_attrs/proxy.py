from typing import TypeVar, Generic, Type

from .types import PARSEABLE

ProxyType = TypeVar("ProxyType", bound=PARSEABLE)


class ApiProxy(Generic[ProxyType]):
    type: Type[ProxyType]
    full_name: str
    type_name: str
    
    def __init__(self, cls: Type[ProxyType]):
        self.type = cls
        self.type_name = cls.__name__
        self.full_name = cls.__module__ + "." + self.type_name
    
    def get_type(self) -> Type[ProxyType]:
        ret = self.type
        return ret
