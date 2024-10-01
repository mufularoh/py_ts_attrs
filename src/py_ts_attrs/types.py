import typing
import attr
import enum
from typing import TypeVar, Union, Optional, Type, List, Dict, Any

from .exportable_enum import ExportableEnum
from .base import ApiDataBase


class LoadError(Exception):
    pass

class ConfigurationError(Exception):
    pass

class UnknownFieldType(Exception):
    pass

class FieldWithoutDefinition(Exception):
    pass
    
T = TypeVar("T", bound=attr.AttrsInstance)

PARSEABLE = Union[Type[ApiDataBase], Type[enum.Enum], Type[ExportableEnum]]

class Partial:
    @staticmethod
    def is_optional(field: attr.Attribute) -> bool:
        origin = getattr(field.type, "__origin__", None)
        args = getattr(field.type, "__args__", None)

        if origin != Union or not args or not any(t == type(None) for t in args):
            return False
        return True

    @staticmethod
    def generate_cls(based_on: Type[T]) -> Type[T]:
        original_fields = attr.fields(based_on)

        fields = {}

        new_annotations = {}

        for f in original_fields:
            new_field = attr.field(default=None)
            new_field.type = Optional[f.type] if not Partial.is_optional(f) else f.type
            fields[f.name] = new_field
            new_annotations[f.name] = new_field.type

        ret = attr.make_class(
            f"Partial_{based_on.__name__}",
            fields,
            bases=(based_on, )
        )
        ret.__annotations__ = new_annotations

        return ret

@attr.s
class ProcessedFieldV2:
    name: str = attr.ib()
    required: bool = attr.ib()
    type: str = attr.ib()


@attr.s
class ProcessingResultV2:
    full_name: str = attr.ib()
    type_name: str = attr.ib()
    fields: List[ProcessedFieldV2] = attr.ib()
    definition: str = attr.ib()
    additional_types: List['ProcessingResultV2'] = attr.ib()
    additional_imports: Dict[str, List[str]] = attr.ib()
    additionally_load: Optional[List[PARSEABLE]] = attr.ib()
    export_values: Optional[List] = attr.ib(default=None)
    export_values_name: Optional[str] = attr.ib(default=None)
    additional_code: Optional[str] = attr.ib(default=None)
    compound: Optional[List[str]] = attr.ib(default=None)


@attr.s
class FieldProcessingResultV2:
    type: str = attr.ib()
    additionally_load: List[PARSEABLE] = attr.ib()
    additionally_import: Dict[str, List[str]] = attr.ib()
    classes_tree: List[str] = attr.ib()
    optional: bool = attr.ib(default=False)




@attr.s
class FieldDefinition:
    name: str = attr.ib()
    type: Type = attr.ib()
    origin: Optional[Type] = attr.ib()
    args: Optional[List[Type]] = attr.ib()
    default_value: Optional[Any] = attr.ib(default=None)
    forced_type: Optional[str] = attr.ib(default=None)

    
    @classmethod
    def create(cls, name: str, field_type: typing.Type, default_value: Optional[Any] = None) -> "FieldDefinition":
        return cls(
            name=name,
            type=field_type,
            origin=getattr(field_type, "__origin__", None),
            args=getattr(field_type, "__args__", []),
            default_value=default_value
        )


@attr.s
class TypeDefinition:
    actual_type: Type = attr.ib()
    ts_type: str = attr.ib()


@attr.s
class DictTypesDefinition:
    key: TypeDefinition = attr.ib()
    value: TypeDefinition = attr.ib()


class UnionDifferentiator:
    type: str
    check: str
    def __init__(self, input_type: str, check: str):
        self.type = input_type
        self.check = check

    def render(self, union_type: str) -> str:
        return f"""export function Is__{self.type}(obj: {union_type}): obj is {self.type} {{return ({self.check})(obj);}}"""

class UnionType:
    name: str
    types: List[str]
    differentiators: Optional[List[UnionDifferentiator]]
    additional: str
    def __init__(self, name: str, *, 
                 differentiators: Optional[List[UnionDifferentiator]] = None, 
                 input_types: Optional[List[str]] = None, 
                 additional_code: Optional[str] = None):
        self.name = name
        if differentiators is not None:
            self.types = [x.type for x in differentiators]
        else:
            assert input_types is not None
            self.types = input_types
        self.differentiators = differentiators
        self.additional = additional_code or ""

    def to_processing_result(self, module_name: str) -> ProcessingResultV2:
        return ProcessingResultV2(
            full_name=f"{module_name}.{self.name}",
            type_name=self.name,
            fields=[], definition=" | ".join(self.types), additional_types=[], additional_imports={},
            additionally_load=[], export_values=None, export_values_name=None,
            additional_code=self.render_differentiators() + self.additional
        )

    def render_differentiators(self) -> str:
        if not self.differentiators:
            return ""
        return "\n".join([x.render(self.name) for x in self.differentiators])


class DoNotExport:
    pass
