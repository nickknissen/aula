from dataclasses import dataclass, field

from .base import AulaDataClass


@dataclass
class WidgetConfiguration(AulaDataClass):
    widget_id: str
    name: str
    widget_supplier: str
    widget_type: str
    placement: str
    is_secure: bool
    can_access_on_mobile: bool
    aggregated_display_mode: str
    _raw: dict | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict) -> "WidgetConfiguration":
        widget = data.get("widget", {})
        return cls(
            widget_id=widget.get("widgetId", ""),
            name=widget.get("name", ""),
            widget_supplier=widget.get("widgetSupplier", ""),
            widget_type=widget.get("type", ""),
            placement=data.get("placement", ""),
            is_secure=widget.get("isSecure", False),
            can_access_on_mobile=widget.get("canAccessOnMobile", False),
            aggregated_display_mode=data.get("aggregatedDisplayMode", ""),
            _raw=data,
        )
