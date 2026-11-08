from collections.abc import Sequence
from typing import Any, NamedTuple, Self

from ..models import Child
from ..utils.mapping import get_in


class WidgetContext(NamedTuple):
    child_filter: list[str]
    institution_filter: list[str]
    session_uuid: str

    @classmethod
    def from_children(cls, children: Sequence[Child], profile_context: dict[str, Any]) -> Self:
        child_filter = [child.user_id for child in children if child.user_id]
        if not child_filter:
            raise ValueError("None of the children has a UniLogin (user_id)")
        session_uuid = get_in(profile_context, "data.userId")
        if not session_uuid:
            raise ValueError("The profile context does not name the guardian (data.userId)")
        return cls(
            child_filter=child_filter,
            institution_filter=list(
                dict.fromkeys(
                    child.institution_code for child in children if child.institution_code
                )
            ),
            session_uuid=str(session_uuid),
        )
