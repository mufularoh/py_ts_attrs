import enum
from collections import OrderedDict
from typing import List, Set, Type, get_type_hints, Union, Dict, Callable, Optional

import attr

from .field_processing import ApiDataField, ExtraDataField
from .proxy import ApiProxy
from .types import FieldWithoutDefinition, ProcessedFieldV2, ProcessingResultV2, PARSEABLE, FieldDefinition
from .base import ApiDataBase


class ApiDataTS:
    cls: PARSEABLE
    name: str
    type_name: str
    module: str
    classes_tree: List[str]
    processors: Dict[str, Union[ApiDataField, str]]
    additional_imports: Dict[str, List[str]]
    is_enum: bool
    get_proxy: Callable[[str], Optional[ApiProxy]]
    also_process_module_keys: Set[str]

    installed_apps: List[str]

    def __init__(self,
                 cls: PARSEABLE,
                 classes_tree: List[str],
                 get_proxy: Callable[[str],
                 Optional[ApiProxy]],
                 also_process_module_keys: Set[str],
                 installed_apps: List[str]
                 ):
        self.name = cls.__name__
        self.type_name = self.name
        if issubclass(cls, ApiDataBase):
            self.type_name = cls.CUSTOM_TS_TYPE_NAME or self.name
        self.module = cls.__module__
        self.cls = cls
        self.get_proxy = get_proxy
        self.also_process_module_keys = also_process_module_keys
        self.installed_apps = installed_apps
        if issubclass(cls, ApiDataBase) or getattr(cls, "_API_DATA", False):
            self.is_enum = False
            self.classes_tree = classes_tree + [self.name]
            self.processors = OrderedDict()
            self.additional_imports = {}
            self.additional_imports.update(getattr(cls, "CUSTOM_IMPORTS", {}))

            custom_ts_type = getattr(cls, "CUSTOM_TS_TYPE", {})
            custom_representation = getattr(cls, "CUSTOM_REPRESENTATION", {})
            omit_in_representation = getattr(cls, "OMIT_IN_REPRESENTATION", [])
            custom_ts_fields = getattr(cls, "CUSTOM_TS_FIELDS", {})

            # noinspection PyDataclass
            for input_field in attr.fields(cls):
                if input_field.name in custom_ts_type:
                    self.processors[input_field.name] = custom_ts_type[input_field.name]
                else:
                    definition = None
                    if input_field.name in custom_representation:
                        hints = get_type_hints(custom_representation[input_field.name])
                        return_hint: Optional[type] = hints.get("return", None)
                        if not return_hint:
                            raise FieldWithoutDefinition(
                                f"Define return type in CUSTOM_REPRESENTATION for {' -> '.join(classes_tree)} -> {input_field.name}")
                        definition = FieldDefinition.create(name=input_field.name, field_type=return_hint)
                    elif input_field not in omit_in_representation:
                        definition = FieldDefinition.create(name=input_field.name, field_type=input_field.type)
                    if definition:
                        self.processors[input_field.name] = ApiDataField.processor(definition, [self.name])
            for name, forced_type in custom_ts_fields.items():
                self.processors[name] = ExtraDataField(FieldDefinition(
                    name=name, type=cls, forced_type=forced_type, args=None, origin=None
                ), [self.name])
        else:
            self.is_enum = True

    @staticmethod
    def _process_enum(enum_cls: Type[enum.Enum]) -> ProcessingResultV2:
        values_for_export = None
        if getattr(enum_cls, "_EXPORT_VALUES", False):
            exporter = getattr(enum_cls, "values_for_export", None)
            if exporter:
                values_for_export = exporter()
            else:
                values_for_export = enum_cls._member_map_.values()

        return ProcessingResultV2(
            full_name=enum_cls.__module__ + "." + enum_cls.__name__, type_name=enum_cls.__name__, fields=[],
            definition=" | ".join([
                (f"\"{value.value}\"" if issubclass(enum_cls, str) else f"{value.value}")
                for value in enum_cls._member_map_.values()
            ]),
            additional_types=[], additional_imports={}, additionally_load=[],
            export_values=[value.value for value in values_for_export] if values_for_export else None,
            export_values_name=getattr(enum_cls, "_EXPORT_VALUES_NAME", None)
        )

    def process(self) -> List[ProcessingResultV2]:
        if self.is_enum:
            try:
                assert issubclass(self.cls, enum.Enum)
                return [self._process_enum(self.cls)]
            except Exception:
                print(self.cls.__dict__)
                print(self.name, self.module, self.classes_tree)
                raise

        additional_types: List[ProcessingResultV2] = []
        additional_types_used: Set[str] = set()
        fields: List[ProcessedFieldV2] = []
        additional_imports: Dict[str, List[str]] = self.additional_imports
        additionally_load: List[PARSEABLE] = []
        definition: str = ""

        def process_additionals(additionals: List[PARSEABLE], imports: Dict[str, List[str]], classes_tree: List[str]):
            for additional_type in additionals:
                proxy_key = additional_type.__module__ + "." + additional_type.__name__
                do_embed = (
                    additional_type.__module__ == self.module or additional_type.__module__.split(".")[ -1] != "dto" or \
                    not any( additional_type.__module__.startswith(app) for app in self.installed_apps)) and \
                    not self.get_proxy( proxy_key) and additional_type.__module__ not in self.also_process_module_keys

                additional_name = getattr(additional_type, "name", additional_type.__name__)

                if do_embed and additional_name not in additional_types_used:
                    additional_types_used.add(additional_name)
                    if issubclass(additional_type, enum.Enum):
                        additional_types.append(self._process_enum(additional_type))
                    else:
                        additional_results: List[ProcessingResultV2] = ApiDataTS(
                            additional_type,
                            self.classes_tree,
                            self.get_proxy,
                            self.also_process_module_keys,
                            self.installed_apps
                        ).process()
                        for additional_result in additional_results:
                            additional_types.append(ProcessingResultV2(
                                full_name=additional_result.full_name,
                                type_name=additional_result.type_name,
                                fields=additional_result.fields,
                                definition=additional_result.definition,
                                additional_types=[], additional_imports={}, additionally_load=[],
                                additional_code=additional_result.additional_code,
                                compound=additional_result.compound
                            ))
                            additional_imports.update(additional_result.additional_imports)
                            assert additional_result.additionally_load is not None
                            process_additionals(additional_result.additionally_load, imports, classes_tree + [additional_result.type_name])
                            for additional_import_module, additional_import_names in additional_result.additional_imports.items():
                                if not additional_import_module in additional_imports:
                                    additional_imports[additional_import_module] = []
                                for n in additional_import_names:
                                    if not n in additional_imports[additional_import_module]:
                                        additional_imports[additional_import_module].append(n)
                else:
                    additionally_load.append(additional_type)

        for field_name, processor in self.processors.items():
            if type(processor) == str:
                fields.append(ProcessedFieldV2(
                    name=field_name,
                    required=True,
                    type=processor
                ))
            else:
                assert isinstance(processor, ApiDataField)
                processed = processor.process()
                fields.append(ProcessedFieldV2(
                    name=field_name,
                    required=not processed.optional,
                    type=processed.type
                ))
                additional_imports.update(processed.additionally_import)
                additionally_load += processed.additionally_load
                process_additionals(processed.additionally_load, additional_imports, self.classes_tree + [field_name])

        compound = getattr(self.cls, "COMPOUND", None)
        return [ProcessingResultV2(
            full_name=self.cls.__module__ + "." + self.cls.__name__,
            type_name=self.type_name,
            fields=fields,
            definition=definition,
            additional_types=[],
            additional_imports=additional_imports,
            additionally_load=additionally_load,
            compound=compound
        )] + additional_types
