import attr
import typing

from .types import LoadError, FieldDefinition, UnknownFieldType
from .base import ApiDataBase
from .field_processing import ApiDataField

T = typing.TypeVar("T", bound=ApiDataBase)


class ApiData(ApiDataBase, typing.Generic[T]):
    @classmethod
    def rec_load(cls, input_data: typing.Any, input_cls: typing.Type[T], field_tree: typing.List[str]) -> T:
        if type(input_data) != dict:
            raise LoadError(" -> ".join(field_tree) + ": Not a Dict while Loadable", input_data)
        input_fields = [x for x in attr.fields(input_cls) if x.init]
        ret_kwargs = {}
        
        for input_field in input_fields:
            field_name = input_field.name
            field_type = input_field.type
            field_value = input_data.get(field_name, None)
            try:
                if getattr(field_type, "__origin__", None) == typing.Union and \
                        not any(t == type(None) for t in getattr(field_type, "__args__", [])) and \
                        not field_name in input_cls.CUSTOM_LOAD:
                    raise UnknownFieldType(" -> ".join(field_tree) + ": Union Field \"{0}\" not in CUSTOM_LOAD".format(field_name))
                if field_name in input_cls.CUSTOM_LOAD:
                    if input_cls.CUSTOM_LOAD[field_name] is not None:
                        ret_kwargs[field_name] = input_cls.CUSTOM_LOAD[field_name](input_data)
                else:
                    ret_kwargs[field_name] = ApiDataField.processor(FieldDefinition.create(
                        field_name,
                        field_type,
                        default_value=input_field.default
                    ), field_tree + [field_name]).load(
                        field_value,
                        field_tree + [field_name]
                    )

            except TypeError:
                raise LoadError(" -> ".join(field_tree) + ": unknown field type: {0} ({1})".format(field_type, field_name))
        # noinspection PyArgumentList
        return input_cls(**ret_kwargs)
    
    @classmethod
    def load_from_dict(cls, value: dict) -> T:
        return cls.rec_load(value, cls, [cls.__name__])  # type: ignore

    def __iter__(self):
        if not hasattr(self, '__attrs_attrs__'):
            raise StopIteration
        for field in attr.fields(self.__class__):
            value = getattr(self, field.name, None)
            if (value is not None or field.name in self.FORCE_NONE) and field.name not in self.OMIT_IN_REPRESENTATION:
                if field.name in self.CUSTOM_REPRESENTATION:
                    yield field.name, self.CUSTOM_REPRESENTATION[field.name](value)
                else:
                    processor = ApiDataField.processor(FieldDefinition.create(
                        name=field.name,
                        field_type=field.type,
                        default_value=field.default
                    ), [])

                    represented = processor.represent(self)
                    yield field.name, represented
    
    def represent(self):
        return dict(self)
    
