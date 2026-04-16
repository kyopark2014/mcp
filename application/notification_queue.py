import streamlit as st
import logging

logger = logging.getLogger("notification_queue")


class NotificationQueue:
    """A queue that renders Streamlit output in order.

    Creates ``st.empty()`` slots on demand to show agent output and tool
    inputs/results sequentially.
    """

    def __init__(self, container=None):
        self._container = container
        self._streaming_slot = None
        self._tool_slots: dict[str, object] = {}
        self._tool_names: dict[str, str] = {}

    def reset(self):
        self._streaming_slot = None
        self._tool_slots = {}
        self._tool_names = {}

    def _new_slot(self):
        if self._container is not None:
            return self._container.empty()
        return st.empty()

    # ---- public API ----

    def notify(self, message: str):
        """Append an info-style notice in a new slot."""
        self._streaming_slot = None
        self._new_slot().info(message)

    def respond(self, message: str):
        """Append a markdown response in a new slot."""
        self._streaming_slot = None
        self._new_slot().markdown(message)

    def stream(self, message: str):
        """Repeatedly update streaming text in the same slot."""
        if self._streaming_slot is None:
            self._streaming_slot = self._new_slot()
        self._streaming_slot.markdown(message)

    def result(self, message: str):
        """Render the final result as markdown; overwrites the streaming slot if any."""
        if self._streaming_slot is not None:
            self._streaming_slot.markdown(message)
            self._streaming_slot = None
        else:
            self._new_slot().markdown(message)

    def tool_update(self, tool_use_id: str, message: str):
        """Show info in a slot reused or created per ``tool_use_id``."""
        if tool_use_id not in self._tool_slots:
            self._streaming_slot = None
            self._tool_slots[tool_use_id] = self._new_slot()
        self._tool_slots[tool_use_id].info(message)

    def register_tool(self, tool_use_id: str, name: str):
        self._tool_names[tool_use_id] = name

    def get_tool_name(self, tool_use_id: str) -> str:
        return self._tool_names.get(tool_use_id, "")
