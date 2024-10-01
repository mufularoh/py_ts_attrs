import re

class CamelCaseHyphenation(object):
    @classmethod
    def hyphens_to_camelcase(cls, val: str, separator: str = '-', capitalize: bool = False) -> str:
        def camelcase():
            yield str.lower
            while True:
                yield str.capitalize
        
        c = camelcase()
        ret = "".join(next(c)(x) if x else '' for x in val.split(separator))
        if capitalize:
            ret = ret[:1].upper() + ret[1:]
        return ret
    
    @classmethod
    def camelcase_to_hyphens(cls, name: str) -> str:
        s1 = re.sub('(.)([A-Z][a-z]+)', r'\1-\2', name)
        return re.sub('([a-z0-9])([A-Z])', r'\1-\2', s1).lower()
