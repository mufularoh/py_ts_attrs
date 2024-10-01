import attr
import abc

import enum
import inspect
import typing
from collections import defaultdict
from datetime import datetime, date
from decimal import Decimal
from typing import ForwardRef

from . import types
from .base import ApiDataBase
from .enums import parse_enum
from .datetime import parse_date, format_date


class Dummy:
    pass


class ApiDataField:
    class NoDefaultValue(Exception):
        pass

    field: types.FieldDefinition
    classes_tree: typing.List[str]

    additionally_load: typing.List[types.PARSEABLE]
    already_used_additional: typing.Set[str]
    additionally_import: typing.Dict[str, typing.List[str]]
    optional: bool

    @abc.abstractmethod
    @staticmethod
    def check(field: types.FieldDefinition) -> bool: ...

    def __init__(self, field: types.FieldDefinition, classes_tree: typing.List[str]):
        self.field = field
        self.classes_tree = classes_tree

        self.additionally_load = []
        self.already_used_additional = set()
        self.additionally_import = defaultdict(list)
        self.optional = False

    @abc.abstractmethod
    def process(self) -> types.FieldProcessingResultV2: ...

    def load(self, input_value: typing.Any, class_tree: typing.List[str]):
        if input_value is None and self.field.default_value != attr.NOTHING:
            return self.field.default_value

        raise self.NoDefaultValue(class_tree, self.field.name)

    def represent(self, cls_exemplar):
        return getattr(cls_exemplar, self.field.name, None)

    @classmethod
    def processor(cls, field: types.FieldDefinition, classes_tree: typing.List[str]) -> "ApiDataField":
        for subclass in cls.__subclasses__():
            if subclass.check(field):
                return subclass(field, classes_tree)
        raise types.UnknownFieldType(f"Unknown field type: {' -> '.join(classes_tree)} -> {field.name}: {field.type}")

    def process_subclass(self, name: str, t: typing.Type[ApiDataBase]) -> types.FieldProcessingResultV2:
        ret = self.__class__.mro()[1].processor(types.FieldDefinition.create(
            name=name,
            field_type=t
        ), classes_tree=self.classes_tree).process()
        for additional_type in ret.additionally_load:
            if additional_type.__name__ not in self.already_used_additional:
                self.already_used_additional.add(additional_type.__name__)
                self.additionally_load.append(additional_type)
        return ret

    def ret(self, field_type: str) -> types.FieldProcessingResultV2:
        return types.FieldProcessingResultV2(
            type=field_type,
            optional=self.optional,
            additionally_load=self.additionally_load,
            classes_tree=self.classes_tree,
            additionally_import=self.additionally_import
        )



class ExtraDataField(ApiDataField):
    @staticmethod
    def check(field: types.FieldDefinition) -> bool:
        return bool(field.forced_type)
    
    def process(self) -> types.FieldProcessingResultV2:
        assert self.field.forced_type is not None
        return types.FieldProcessingResultV2(
            type=self.field.forced_type,
            additionally_load=[],
            additionally_import={},
            classes_tree=[]
        )


class UnionDataField(ApiDataField):
    @staticmethod
    def check(field: types.FieldDefinition) -> bool:
        return field.origin == typing.Union
    
    def _get_union_types(self) -> typing.List[types.TypeDefinition]:
        union_type_names = set()
        ret: typing.List[types.TypeDefinition] = []
        assert self.field.args is not None
        for i, t in enumerate(self.field.args):
            if t == type(None):
                self.optional = True
            else:
                parsed = self.process_subclass(f"{self.field.name}_{i}", t)
                if not parsed.type in union_type_names:
                    union_type_names.add(parsed.type)
                    ret.append(types.TypeDefinition(ts_type=parsed.type, actual_type=t))

        return ret
    
    def load(self, input_value: typing.Any, class_tree: typing.List[str]):
        try:
            return super().load(input_value, class_tree)
        except self.NoDefaultValue:
            pass
        union_types = self._get_union_types()
        if self.optional and input_value is None:
            return None
        for t in union_types:
            try:
                return ApiDataField.processor(types.FieldDefinition.create(f"{self.field.name}[union]", t.actual_type), class_tree).load(input_value, class_tree)
            except types.LoadError as e:
                print(e)
        raise types.LoadError(f"Type Mismatch: {' -> '.join(class_tree)} -> {self.field.name}: " f"{type(input_value)} is not in Union[{', '.join([t.actual_type.__name__ for t in union_types])}]")
    
    def represent(self, cls_exemplar):
        ret = getattr(cls_exemplar, self.field.name, None)
        assert self.field.args is not None
        for t in self.field.args:
            try:
                if (t == type(ret) or getattr(t, "__origin__", None) == type(ret) or (inspect.isclass(t) and (issubclass(t, type(ret)) or issubclass(type(ret), t)))) and t != type(None):
                    return ApiDataField.processor(types.FieldDefinition.create(self.field.name, t), [self.field.name]).represent(cls_exemplar)
            except TypeError:  # python3.6
                pass
                
        return None

    def process(self) -> types.FieldProcessingResultV2:
        resulting_types = self._get_union_types()
        return self.ret(" | ".join(sorted(list([x.ts_type for x in resulting_types]))))


class ListDataField(ApiDataField):
    @staticmethod
    def check(field: types.FieldDefinition) -> bool:
        return field.origin in (typing.List, list)
    
    def process(self) -> types.FieldProcessingResultV2:
        assert self.field.args is not None
        parsed = self.process_subclass(f"{self.field.name}[arg]", self.field.args[0])
        output_type = f"({parsed.type})[]" if "|" in parsed.type else f"{parsed.type}[]"
        return self.ret(output_type)
    
    def load(self, input_value: typing.Any, class_tree: typing.List[str]):
        try:
            return super().load(input_value, class_tree)
        except self.NoDefaultValue:
            pass
        if type(input_value) != list:
            raise types.LoadError(f"Type Mismatch: {' -> '.join(class_tree)} -> {self.field.name}: {type(input_value)} is not a list!")
        ret = []
        assert self.field.args is not None
        for i, x in enumerate(input_value):
            ret.append(
                ApiDataField.processor(types.FieldDefinition.create(f"{self.field.name}[{i}]", self.field.args[0]), class_tree).load(x, class_tree)
            )
        return ret
    
    def represent(self, cls_exemplar):
        ret = getattr(cls_exemplar, self.field.name, None)
        result = []
        if ret is not None:
            assert self.field.args is not None
            for _, value in enumerate(ret):
                dummy = Dummy()
                setattr(dummy, self.field.name, value)
                result.append(
                    ApiDataField.processor(types.FieldDefinition.create(self.field.name, self.field.args[0]), [self.field.name]).represent(dummy)
                )
            return result
        return None


class TupleDataField(ApiDataField):
    @staticmethod
    def check(field: types.FieldDefinition) -> bool:
        return field.origin in (typing.Tuple, tuple)
    
    def _get_tuple_types(self) -> typing.List[types.TypeDefinition]:
        resulting_types = []
        assert self.field.args is not None
        for i, t in enumerate(self.field.args):
            parsed = self.process_subclass(f"{self.field.name}_{i}", t)
            resulting_types.append(types.TypeDefinition(actual_type=t, ts_type=parsed.type))
        return resulting_types
    
    def process(self) -> types.FieldProcessingResultV2:
        resulting_types = self._get_tuple_types()
        output_type = "[" + ", ".join([x.ts_type for x in resulting_types]) + "]"
        return self.ret(output_type)
    
    def load(self, input_value: typing.Any, class_tree: typing.List[str]):
        try:
            return super().load(input_value, class_tree)
        except self.NoDefaultValue:
            pass
        tuple_types = self._get_tuple_types()
        if type(input_value) != list:
            raise types.LoadError(f"Type Mismatch: {' -> '.join(class_tree)} -> {self.field.name}: {type(input_value)} is not a list!")
        if len(input_value) != len(tuple_types):
            raise types.LoadError(
                f"Length Mismatch: {' -> '.join(class_tree)} -> {self.field.name}: "
                f"expected {len(tuple_types)}, got {len(input_value)}"
            )
        ret = []
        for i, (t, v) in enumerate(zip(tuple_types, input_value)):
            value = ApiDataField.processor(types.FieldDefinition.create(f"{self.field.name}[{i}]", t.actual_type), class_tree).load(v, class_tree + [self.field.name])
            ret.append(value)
        return tuple(ret)
    
    def represent(self, cls_exemplar):
        ret = getattr(cls_exemplar, self.field.name, None)
        if ret is not None:
            tuple_types = self._get_tuple_types()
            result = []
            for (t, v) in zip(tuple_types, ret):
                dummy = Dummy()
                setattr(dummy, self.field.name, v)
                result.append(
                    ApiDataField.processor(types.FieldDefinition.create(self.field.name, t.actual_type), []).represent(dummy)
                )
            return result
        return None


class AnyDataField(ApiDataField):
    @staticmethod
    def check(field: types.FieldDefinition) -> bool:
        return field.type == typing.Any
    
    def process(self) -> types.FieldProcessingResultV2:
        return self.ret("any")
    
    def load(self, input_value: typing.Any, class_tree: typing.List[str]):
        try:
            return super().load(input_value, class_tree)
        except self.NoDefaultValue:
            pass
        return input_value


class PlainDictDataField(ApiDataField):
    @staticmethod
    def check(field: types.FieldDefinition) -> bool:
        return field.origin is None and field.type == dict
    
    def process(self) -> types.FieldProcessingResultV2:
        return self.ret(f"Record<string, any>")
    
    def load(self, input_value: typing.Any, class_tree: typing.List[str]):
        try:
            return super().load(input_value, class_tree)
        except self.NoDefaultValue:
            pass
        if type(input_value) != dict:
            raise types.LoadError(f"Type Mismatch: {' -> '.join(class_tree)} -> {self.field.name}: {type(input_value)} is not a dict!")
        return input_value


class DictDataField(ApiDataField):
    @staticmethod
    def check(field: types.FieldDefinition) -> bool:
        return field.origin in (typing.Dict, dict)
    
    def _get_definition(self) -> types.DictTypesDefinition:
        assert self.field.args is not None
        return types.DictTypesDefinition(
            key=types.TypeDefinition(actual_type=self.field.args[0], ts_type=self.process_subclass(f"{self.field.name}_key", self.field.args[0]).type),
            value=types.TypeDefinition(actual_type=self.field.args[1], ts_type=self.process_subclass(f"{self.field.name}_value", self.field.args[1]).type),
        )
    
    def process(self) -> types.FieldProcessingResultV2:
        definition = self._get_definition()
        return self.ret(f"Record<{definition.key.ts_type}, {definition.value.ts_type}>")
    
    def load(self, input_value: typing.Any, class_tree: typing.List[str]):
        try:
            return super().load(input_value, class_tree)
        except self.NoDefaultValue:
            pass
        if type(input_value) != dict:
            raise types.LoadError(f"Type Mismatch: {' -> '.join(class_tree)} -> {self.field.name}: {type(input_value)} is not a dict!")
        definition = self._get_definition()
        ret = {}
        for key, value in input_value.items():
            
            actual_types = [definition.key.actual_type]
            actual_types_origin = getattr(definition.key.actual_type, "__origin__", None)
            actual_types_args = getattr(definition.key.actual_type, "__args__", [])
            
            if actual_types_origin == typing.Union and not any(x == type(None) for x in actual_types_args):
                actual_types = actual_types_args
            
            if type(key) not in actual_types:
                if type(key) == str and len(actual_types) == 1 and inspect.isclass(actual_types[0]) and issubclass(actual_types[0], enum.Enum):
                    actual_key = parse_enum(actual_types[0], key)
                    if actual_key:
                        key = actual_key
                    else:
                        raise types.LoadError(
                            f"Type Mismatch: {' -> '.join(class_tree)} -> "
                            f"{self.field.name}: key ({key}, {type(key)}) is not {actual_types}!"
                        )
                else:
                    raise types.LoadError(
                        f"Type Mismatch: {' -> '.join(class_tree)} -> "
                        f"{self.field.name}: key ({key}, {type(key)}) is not {actual_types}!"
                    )
                    
            actual_value = ApiDataField.processor(
                types.FieldDefinition.create(
                    f"{self.field.name}[{str(key)}]", definition.value.actual_type
                ), class_tree
            ).load(value, class_tree + [self.field.name])
            ret[key] = actual_value
        return ret
    
    def represent(self, cls_exemplar):
        ret = getattr(cls_exemplar, self.field.name, None)
        if ret is not None:
            result = {}
            definition = self._get_definition()
            for k, v in ret.items():
                dummy_key = Dummy()
                setattr(dummy_key, self.field.name, k)
                dummy_value = Dummy()
                setattr(dummy_value, self.field.name, v)
                result[
                    ApiDataField.processor(types.FieldDefinition.create(self.field.name, definition.key.actual_type), []).represent(dummy_key)
                ] = ApiDataField.processor(types.FieldDefinition.create(self.field.name, definition.value.actual_type), []).represent(dummy_value)
            return result
        return None


class StrDataField(ApiDataField):
    @staticmethod
    def check(field: types.FieldDefinition) -> bool:
        return field.type == str 
    
    def process(self) -> types.FieldProcessingResultV2:
        return self.ret("string")
    
    def load(self, input_value: typing.Any, class_tree: typing.List[str]):
        try:
            return super().load(input_value, class_tree)
        except self.NoDefaultValue:
            pass


        if type(input_value) != str and not isinstance(input_value, str):
            raise types.LoadError(f"Type Mismatch: {' -> '.join(class_tree)} -> {self.field.name}: {type(input_value)} is not a string!")
        
        return input_value


class NumberDataField(ApiDataField):
    @staticmethod
    def check(field: types.FieldDefinition) -> bool:
        return field.type in (int, float)
    
    def process(self) -> types.FieldProcessingResultV2:
        return self.ret("number")
    
    def load(self, input_value: typing.Any, class_tree: typing.List[str]):
        try:
            return super().load(input_value, class_tree)
        except self.NoDefaultValue:
            pass
        if type(input_value) != self.field.type:
            if self.field.type == float and type(input_value) == int:
                return float(input_value)
            elif self.field.type == int and type(input_value) == float:
                return int(input_value)
            else:
                raise types.LoadError(f"Type Mismatch: {' -> '.join(class_tree)} -> {self.field.name}: {type(input_value)} is not a {self.field.type}!")
        
        return input_value


class DecimalDataField(ApiDataField):
    @staticmethod
    def check(field: types.FieldDefinition) -> bool:
        return field.type == Decimal
    
    def process(self) -> types.FieldProcessingResultV2:
        return self.ret("number")
    
    def load(self, input_value: typing.Any, class_tree: typing.List[str]):
        try:
            return super().load(input_value, class_tree)
        except self.NoDefaultValue:
            pass
        if input_value:
            return Decimal(input_value)
        return None
    
    def represent(self, cls_exemplar):
        ret = getattr(cls_exemplar, self.field.name, None)
        if ret is not None:
            return float(ret)


class BoolDataField(ApiDataField):
    @staticmethod
    def check(field: types.FieldDefinition) -> bool:
        return field.type == bool
    
    def process(self) -> types.FieldProcessingResultV2:
        return self.ret("boolean")

    def load(self, input_value: typing.Any, class_tree: typing.List[str]):
        try:
            return super().load(input_value, class_tree)
        except self.NoDefaultValue:
            pass
    
        if type(input_value) != bool:
            raise types.LoadError(f"Type Mismatch: {' -> '.join(class_tree)} -> {self.field.name}: {type(input_value)} is not a boolean!")
    
        return input_value


class EnumDataField(ApiDataField):
    @staticmethod
    def check(field: types.FieldDefinition) -> bool:
        return inspect.isclass(field.type) and issubclass(field.type, enum.Enum) and (issubclass(field.type, str) or issubclass(field.type, int))
    
    def process(self) -> types.FieldProcessingResultV2:
        field_type: typing.Type[enum.Enum] = self.field.type
        self.additionally_load += [field_type]  # type: ignore
        return self.ret(self.field.type.__name__)
    
    def load(self, input_value: typing.Any, class_tree: typing.List[str]):
        try:
            return super().load(input_value, class_tree)
        except self.NoDefaultValue:
            pass
        if type(input_value) != str:
            if type(input_value) == self.field.type:
                return input_value
            raise types.LoadError(f"Type Mismatch: {' -> '.join(class_tree)} -> {self.field.name}: {type(input_value)} is not a string and neither {self.field.type}!")
        actual_value = parse_enum(self.field.type, input_value)
        if not actual_value:
            raise types.LoadError(f"Value Error: {' -> '.join(class_tree)} -> {self.field.name}: {input_value} is not a {self.field.type.__name__}!")
        return actual_value
    
    def represent(self, cls_exemplar):
        ret = getattr(cls_exemplar, self.field.name, None)
        if ret is not None:
            try:
                return ret.value
            except AttributeError:
                if type(ret) == str:
                    return ret
                raise types.LoadError(f"Value Error: {self.field.name}: {ret} is not a {self.field.type.__name__}!")
        return None



class DateDataField(ApiDataField):
    @staticmethod
    def check(field: types.FieldDefinition) -> bool:
        return inspect.isclass(field.type) and issubclass(field.type, date)
    
    def process(self) -> types.FieldProcessingResultV2:
        return self.ret("string")
    
    def load(self, input_value: typing.Any, class_tree: typing.List[str]):
        try:
            return super().load(input_value, class_tree)
        except self.NoDefaultValue:
            pass
        return parse_date(input_value, self.field.type == datetime)
    
    def represent(self, cls_exemplar):
        ret = getattr(cls_exemplar, self.field.name, None)
        if ret is not None:
            try:
                return format_date(ret, self.field.type == datetime)
            except AttributeError as e:
                print(self.field)
                raise e
        return None


class ForwardRefDataField(ApiDataField):
    @staticmethod
    def check(field: types.FieldDefinition) -> bool:
        return type(field.type) == ForwardRef and inspect.isclass(field.type.__forward_arg__) and issubclass(field.type.__forward_arg__, ApiDataBase)
    
    def __init__(self, field: types.FieldDefinition, classes_tree: typing.List[str]):
        super().__init__(field, classes_tree)
        self.field.type = self.field.type.__forward_arg__

    def process(self) -> types.FieldProcessingResultV2:
        field_type: types.PARSEABLE = self.field.type  # type: ignore
        self.additionally_load += [field_type]
        return self.ret(getattr(self.field.type, "__forward_arg__"))
    
    def load(self, input_value: typing.Any, class_tree: typing.List[str]):
        try:
            return super().load(input_value, class_tree)
        except self.NoDefaultValue:
            pass
        return self.field.type.load_from_dict(input_value)
    
    def represent(self, cls_exemplar):
        ret = getattr(cls_exemplar, self.field.name, None)
        if ret is not None:
            return ret.represent()
        return None


class SubclassDataField(ApiDataField):
    @staticmethod
    def check(field: types.FieldDefinition) -> bool:
        ret = inspect.isclass(field.type) and (issubclass(field.type, ApiDataBase) or getattr(field.type, "_API_DATA", False))
        return ret
    
    def process(self) -> types.FieldProcessingResultV2:
        field_type: types.PARSEABLE = self.field.type  # type: ignore
        self.additionally_load += [field_type]
        return self.ret(self.field.type.__name__)

    def load(self, input_value: typing.Any, class_tree: typing.List[str]):
        try:
            return super().load(input_value, class_tree)
        except self.NoDefaultValue:
            pass
        return self.field.type.load_from_dict(input_value)

    def represent(self, cls_exemplar):
        ret = getattr(cls_exemplar, self.field.name, None)
        try:
            result = ret.represent() if ret is not None else None
        except types.LoadError:
            raise
        return result

class PartialSubclassDataField(ApiDataField):
    def __init__(self, field: types.FieldDefinition, classes_tree: typing.List[str]):
        super().__init__(field, classes_tree)
        assert self.field.args is not None
        self.partial_cls = types.Partial.generate_cls(self.field.args[0])

    @staticmethod
    def check(field: types.FieldDefinition) -> bool:
        if field.origin and inspect.isclass(field.origin) and issubclass(field.origin, types.Partial):
            if not field.args or len(field.args) != 1 or not inspect.isclass(field.args[0]) or not issubclass(field.args[0], ApiDataBase):
                raise types.ConfigurationError(f"Partial[] can only be applied to ApiData values: {field.name}")
            return True
        return False

    def process(self) -> types.FieldProcessingResultV2:
        assert self.field.args is not None
        field_type: typing.Type[types.PARSEABLE] = self.field.args[0]
        self.additionally_load += [field_type]
        return self.ret(f"Partial<{field_type.__name__}>")

    def load(self, input_value: typing.Any, class_tree: typing.List[str]):
        try:
            return super().load(input_value, class_tree)
        except self.NoDefaultValue:
            pass
        return self.partial_cls.load_from_dict(input_value)

    def represent(self, cls_exemplar):
        ret = getattr(cls_exemplar, self.field.name, None)
        try:
            result = ret.represent() if ret is not None else None
        except types.LoadError:
            # print(self.field, cls_exemplar)
            raise
        return result
