import importlib
import inspect
import json
import types
from collections import defaultdict
from pathlib import Path
from typing import Optional,  List, Dict, Set, Union, Callable, Tuple

import attr

from .parse import ApiDataTS
from .proxy import ApiProxy
from .types import ProcessingResultV2,  PARSEABLE, DoNotExport,  UnionType
from .exportable_enum import ExportableEnum
from .base import ApiDataBase

from .text_utils import CamelCaseHyphenation

@attr.s
class AppFolder:
    path: Path = attr.ib()
    name: str = attr.ib()

@attr.s
class ModuleContents:
    contents: List[Union[ApiProxy, ApiDataBase, ExportableEnum]] = attr.ib()
    also_process_module_keys: Set[str] = attr.ib()
    with_overrided_outputs: List[Tuple[List[PARSEABLE], Tuple[Path, str]]] = attr.ib()
@attr.s(auto_attribs=True)
class TypeScriptSettings:
    output_path: Path
    import_root: str
    default_folder: str
    installed_apps: List[str]
    app_folders: List[AppFolder]
    write_output: bool

class TypescriptFile:
    path: Path
    sections: List[List[str]]
    name: str
    
    def __init__(self, settings: TypeScriptSettings, sections: List[List[str]], *, module: str, folder: Optional[str] = None, path: Optional[Path] = None):
        self.name = f"{module}.ts"
        if path:
            self.path = path / self.name
        elif folder:
            self.path = settings.output_path / f"{folder}{self.name}"
        else:
            raise Exception(f"Misconfiguration for {self.name}: neither folder nor path is set")
        self.sections = sections


    def generate_code(self):
        return "\n\n".join(["\n".join(section).strip() for section in self.sections])

    @staticmethod
    def _header():
        return [
            f"// This file is generated automatically! Please do not change it manually",
            "// ALL CHANGES WILL BE LOST",
            "",
        ]

    def generate(self, header):
        return ("\n".join(header) + self.generate_code()).strip().replace("\n\n\n", "\n\n")

    def update(self):
        header = self._header()
        header_lines = len(header)
        new_text = self.generate(header)
        try:
            with self.path.open("rt") as f:
                old_full = f.readlines()
                if old_full[header_lines:] == new_text.splitlines(keepends=True)[header_lines:]:
                    # files code is the same
                    return
        except FileNotFoundError:
            pass

        self.path.write_text(new_text)


PROCESSABLE = Union[PARSEABLE, ApiProxy, ExportableEnum, UnionType, ProcessingResultV2]

class PrintableModule:
    settings: TypeScriptSettings
    name: str
    imports: Dict[str, List[str]] 
    additional_imports: Dict[str, List[str]] 
    types: List[str] 
    repository: "ModulesRepository" 
    key: str 
    prefix: str 

    to_process: List[PROCESSABLE] 
    already_processed: Set[str] 
    also_process_module_keys: Set[str] = set()

    custom_already_pulled: Set[str] 

    custom_path: Optional[Path] 
    
    def __init__(self, settings: TypeScriptSettings, name: str, repository: "ModulesRepository", prefix: str = "", *, custom_path: Optional[Path] = None):
        self.settings = settings
        self.name = name
        self.imports = defaultdict(lambda: [])
        self.additional_imports = {}
        self.types = []
        self.repository = repository
        self.already_processed = set()
        self.custom_already_pulled = set()
        self.prefix = prefix
        self.to_process = []
        self.key = self.repository.add(self)
        self.custom_path = custom_path
    
    def import_path(self) -> str:
        return f"{self.settings.import_root}{self.prefix}{self.name}"
    
    def process(self, result: ProcessingResultV2, recursive: bool = True):
        if result.type_name in self.already_processed:
            return
        self.already_processed.add(result.type_name)
        self.additional_imports.update(result.additional_imports)
        
        if recursive:
            additional_parsed_types = [x for x in result.additional_types]
            assert result.additionally_load is not None 
            for additional_type in result.additionally_load:
                additional_type_name = additional_type.__name__
                import_from = self.repository.import_from(additional_type_name)
                if import_from and import_from.import_path() != self.import_path():
                    self.imports[import_from.import_path()].append(additional_type_name)
                else:
                    additional_parsed_types += self.preprocess(additional_type)
                    
            for additional_parsed_type in additional_parsed_types:
                self.process(additional_parsed_type)
                self.additional_imports.update(result.additional_imports)
        
        
        import_from = self.repository.import_from(result.type_name)
        if self.custom_path:
            for ref, names in self.imports.items():
                actual_names = list(set(names))
                for n in actual_names:
                    key = f"{ref}.{n}"
                    if key not in self.custom_already_pulled:
                        self.custom_already_pulled.add(key)
                        pull_from = self.repository.import_from(n)
                        if pull_from:
                            try:
                                to_add = next(p for p in pull_from.to_process if inspect.isclass(p) and p.__name__ == n)
                                for x in pull_from.preprocess(to_add):
                                    self.process(x)
                            except StopIteration:
                                pass

        if import_from and import_from.import_path() != self.import_path() and not self.custom_path:
            self.imports[import_from.import_path()].append(result.type_name)
        else:
            if result.definition:
                ret = []
                if result.export_values:
                    export_variable = result.export_values_name or result.type_name[0].lower() + result.type_name[1:]
                    ret += [
                        f"export const {export_variable} = {json.dumps(result.export_values)} as const;",
                        f"export type {result.type_name} = typeof {export_variable}[number];"
                    ]
                else:
                    ret += [
                        f"export type {result.type_name} = {result.definition};"
                    ]
            else:
                compound = ""
                if result.compound:
                    compound = " & ".join(result.compound) + " & "
                ret = [
                          f"export type {result.type_name} = {compound}{{",
                      ] + [
                          f"    {field.name}{'?' if not field.required else ''}: {field.type},"
                          for field in result.fields
                      ] + [
                          "};"
                      ]
            if result.additional_code:
                ret += [result.additional_code]
            
            self.types.append("\n".join(ret))

    def get_ts(self, folder: Optional[str] = None) -> TypescriptFile:
        folder = None
        path = None
        if self.custom_path:
            path = self.custom_path
        else:
            folder = folder if folder else self.settings.default_folder
        return TypescriptFile(
            self.settings,
            [
                [
                        (
                            "\n".join([
                                f"import {{ {', '.join(sorted(list(set(v))))} }} from \"{k}\";"
                                for k, v in list(self.additional_imports.items()) + list(self.imports.items())
                            ])
                        )
                ] if not self.custom_path else [],
                ["\n\n".join(self.types)],
        ], folder=folder, path=path, module=self.prefix + self.name)
    
    def add(self, to_add: PROCESSABLE):
        self.to_process.append(to_add)
        if isinstance(to_add, ApiProxy):
            self.repository.add_proxy(to_add)
            self.repository.add_import_from(to_add.type_name, self)
        elif isinstance(to_add, UnionType):
            self.repository.add_union(to_add)
        elif isinstance(to_add, ProcessingResultV2):
            pass
        else:
            self.repository.add_import_from(to_add.__name__, self)
        
    def preprocess(self, source: PROCESSABLE) -> List[ProcessingResultV2]:
        if isinstance(source, UnionType):
            return [source.to_processing_result(self.name)]
        elif isinstance(source, ProcessingResultV2):
            return [source]
        ret = ApiDataTS(
            source.get_type() if isinstance(source, ApiProxy) else source,  # type: ignore
            [],
            lambda x: self.repository.proxies.get(x, None),
            self.also_process_module_keys,
            self.settings.installed_apps
        ).process()
        return ret
    
    def set_also_process(self, keys: Set[str]):
        self.also_process_module_keys = keys
    
    def digest(self):
        for p in self.to_process:
            for result in self.preprocess(p):
                self.process(result)



class ModulesRepository:
    _used_already: Dict[str, PrintableModule]
    modules: Dict[str, PrintableModule]
    proxies: Dict[str, ApiProxy]
    unions: List[UnionType] 
    
    def __init__(self):
        self._used_already = {}
        self.modules = {}
        self.proxies = {}
        self.unions = []
    
    def add(self, module: PrintableModule) -> str:
        key = module.settings.default_folder + module.prefix + module.name
        if key not in self.modules:
            self.modules[key] = module
        return key
    
    def add_proxy(self, proxy: ApiProxy):
        self.proxies[proxy.full_name] = proxy
    
    def import_from(self, class_name: str) -> Optional[PrintableModule]:
        ret = self._used_already.get(class_name, None)
        return ret

    def add_union(self, union: UnionType):
        self.unions.append(union)
    
    def add_import_from(self, class_name: str, module: PrintableModule):
        if class_name not in self._used_already:
            self._used_already[class_name] = module


def marked_not_export(cls: PARSEABLE):
    return inspect.isclass(cls) and issubclass(cls, DoNotExport)


def api_setup(settings: TypeScriptSettings):
    regenerate_types = True
    repository = ModulesRepository()
    
    
    def get_module_contents(module_: object) -> ModuleContents:
        ret: List[Union[ApiProxy, ApiDataBase, ExportableEnum]] = []
        also_process = getattr(module_, "ALSO_PROCESS", [])
        to_process = list(vars(module_).values())
        also_process_keys: Set[str] = set()
        with_overrided_outputs: List[Tuple[List[Union[PARSEABLE, UnionType, ProcessingResultV2]], Tuple[Path, str]]] = []
        for also in also_process:
            to_process += list(vars(also).values())
        auto_discover: Optional[Callable[[],Tuple[List[Union[PARSEABLE, UnionType, ProcessingResultV2]], Optional[Tuple[Path, str]]]]] = getattr(module_, "AUTO_DISCOVER", None)
        if auto_discover:
            discovered, output_settings = auto_discover()
            if not output_settings:
                to_process += discovered
            else:
                with_overrided_outputs.append((discovered, output_settings))

        for v in to_process:
            if (
                    (not marked_not_export(v)) and
                    (
                            (inspect.isclass(v) and issubclass(v, ApiDataBase) and attr.has(v) and getattr(v, "__module__", "").startswith(child.name)) or
                            (inspect.isclass(v) and issubclass(v, ExportableEnum) and getattr(v, "__module__", "").startswith(child.name)) or
                            (isinstance(v, ApiProxy))
                    )
            ):
                if v.__module__ in [y.__name__ for y in also_process]:
                    also_process_keys.add(v.__module__)
                ret.append(v)  # type: ignore
        return ModuleContents(
            contents=ret,
            also_process_module_keys=also_process_keys,
            with_overrided_outputs=with_overrided_outputs  # type: ignore
        )
    
    
    also_process_module_keys: Set[str] = set()
    if regenerate_types:
        for child in settings.app_folders:
            if (child.path / "dto.py").exists():
                module_contents = get_module_contents(importlib.import_module(f"{child.name}.dto"))
                if module_contents:
                    module = PrintableModule(settings, child.name.split(".")[-1], repository, f"{child.name.split('.')[0]}-")
                    also_process_module_keys |= module_contents.also_process_module_keys
                    for x in module_contents.contents:
                        if isinstance(x, ApiProxy):
                            module.add(x)
                        else:
                            module.add(x)
                    for contents, overriden_outputs in module_contents.with_overrided_outputs:
                        module = PrintableModule(overriden_outputs[1], repository, "", custom_path=overriden_outputs[0])
                        for x in contents:
                            module.add(x)
    
    for child in app_folders:
        if (child.path / "api.py").exists():
            module_contents = [
                (k, v)
                for k, v in vars(importlib.import_module(f"{child.name}.api")).items()
                if isinstance(v, types.FunctionType) and getattr(v, "is_api_method", False) and getattr(v, "is_v2", False)
            ]
            if module_contents:
                module_api = ApiModule(child.name.split(".")[-1], repository, f"{child.name.split('.')[0]}-")
                for name, handler in module_contents:
                    if regenerate_types:
                        module_api.add(HandlerSignature.get(handler.original))
    
    if write_output:
        for module in repository.modules.values():
            module.set_also_process(also_process_module_keys)
            module.digest()
            module.get_ts().update()
            
    return repository
