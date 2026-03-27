from dataclasses import dataclass, field
from typing import Any

from .base import AulaDataClass


@dataclass
class ProfileMasterData(AulaDataClass):
    institution_profile_id: int
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone_number: str = ""
    mobile_phone: str = ""
    address: str = ""
    postal_code: str = ""
    city: str = ""
    municipality: str = ""
    portal_role: str = ""
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProfileMasterData":
        address_data = data.get("address") or {}
        if isinstance(address_data, str):
            address_str = address_data
            postal_code = ""
            city = ""
        else:
            address_str = address_data.get("street", "")
            postal_code = str(address_data.get("postalCode", ""))
            city = address_data.get("city", "")

        return cls(
            _raw=data,
            institution_profile_id=data.get("institutionProfileId", 0),
            first_name=data.get("firstName", ""),
            last_name=data.get("lastName", ""),
            email=data.get("email", ""),
            phone_number=str(data.get("phoneNumber", "")),
            mobile_phone=str(data.get("mobilePhoneNumber", "")),
            address=address_str,
            postal_code=postal_code,
            city=city,
            municipality=data.get("municipality", ""),
            portal_role=data.get("portalRole", ""),
        )
