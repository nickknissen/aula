import dataclasses
from dataclasses import dataclass


@dataclass
class AulaDataClass:
    def __iter__(self):
        for f in dataclasses.fields(self):
            # Skip raw field and internal list fields
            if f.name == "_raw" or isinstance(getattr(self, f.name, None), list):
                continue
            # Also skip fields that are instances of other AulaDataClass unless explicitly handled
            # This basic iterator might need refinement for nested objects
            if isinstance(getattr(self, f.name, None), AulaDataClass):
                continue
            yield f.name, getattr(self, f.name)
