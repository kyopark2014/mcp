import streamlit as st
import logging

logger = logging.getLogger("strands-agent")


class NotificationQueue:
    """Streamlit 컨테이너를 순차적으로 관리하는 큐.

    st.empty() 슬롯을 on-demand로 생성하여 agent 결과, tool 입력/결과를
    순서대로 표시한다.  기존의 global index / streaming_index 방식을 대체한다.
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
        """info 스타일 알림을 새 슬롯에 추가한다."""
        self._streaming_slot = None
        self._new_slot().info(message)

    def respond(self, message: str):
        """markdown 응답을 새 슬롯에 추가한다."""
        self._streaming_slot = None
        self._new_slot().markdown(message)

    def stream(self, message: str):
        """스트리밍 텍스트를 같은 슬롯에 반복 업데이트한다."""
        if self._streaming_slot is None:
            self._streaming_slot = self._new_slot()
        self._streaming_slot.markdown(message)

    def result(self, message: str):
        """최종 결과를 markdown으로 출력한다. streaming 슬롯이 있으면 덮어쓴다."""
        if self._streaming_slot is not None:
            self._streaming_slot.markdown(message)
            self._streaming_slot = None
        else:
            self._new_slot().markdown(message)

    def tool_update(self, tool_use_id: str, message: str):
        """tool_use_id 기반으로 슬롯을 재사용하거나 새로 생성하여 info를 표시한다."""
        if tool_use_id not in self._tool_slots:
            self._streaming_slot = None
            self._tool_slots[tool_use_id] = self._new_slot()
        self._tool_slots[tool_use_id].info(message)

    def register_tool(self, tool_use_id: str, name: str):
        self._tool_names[tool_use_id] = name

    def get_tool_name(self, tool_use_id: str) -> str:
        return self._tool_names.get(tool_use_id, "")
