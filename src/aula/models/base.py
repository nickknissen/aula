import dataclasses
from dataclasses import dataclass


@dataclass
class AulaDataClass:
    def __iter__(self):
        """Yield (name, value) pairs for all fields except _raw.

        Nested AulaDataClass instances are recursively converted to dicts.
        This enables ``dict(model)`` to produce a complete, serializable representation.
        """
        for f in dataclasses.fields(self):
            if f.name == "_raw":
                continue
            value = getattr(self, f.name)
            if isinstance(value, AulaDataClass):
                value = dict(value)
            elif isinstance(value, list):
                value = [dict(item) if isinstance(item, AulaDataClass) else item for item in value]
            yield f.name, value
