from typing import Dict, Callable, Any, List


class ApiDataBase:
    """
    CUSTOM_LOAD: {field_name: loading_function, ...} where loading_function receives OUTER value for the field
    CUSTOM_IMPORTS: list of additional import for ts autogeneration
    OMIT_IN_REPRESENTATION: list of fields that shouldn't be represented by represent() method or by TS autogeneration
    CUSTOM_REPRESENTATION: {field_name: representing_function, ...}
    CUSTOM_TS_TYPE: {field_name: ts_type, ...}
    STRICT_MODE: when True do not attempts to auto-fill missing values with empty
    FORCE_NONE: Forces None as value for non-existent fields while representing
    """
    
    CUSTOM_LOAD: Dict[str, Callable[[Any], Any]] = {}
    CUSTOM_IMPORTS: Dict[str, List[str]] = {}
    OMIT_IN_REPRESENTATION: List[str] = []
    CUSTOM_REPRESENTATION: Dict[str, Callable[[Any], Any]] = {}
    CUSTOM_TS_TYPE: Dict[str, str] = {}
    CUSTOM_TS_FIELDS: Dict[str, str] = {}
    STRICT_MODE: bool = False
    FORCE_NONE = []
    COMPOUND: List[str] = []
    
    @classmethod
    def load_from_dict(cls, value: dict) -> "ApiDataBase": ...
    
    def represent(self) -> dict: ...

