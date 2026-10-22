from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class EventBus(QObject):
    """Pub/sub para eventos do app — observabilidade e IA."""

    image_opened = Signal(str)
    separation_completed = Signal(int)
    skill_started = Signal(str, str)
    skill_finished = Signal(str, bool)
    channel_adjusted = Signal(str)
    channel_merged = Signal(str)
    channel_deleted = Signal(str)
    channel_reordered = Signal()
    textile_preset_changed = Signal(str)
    psd_exported = Signal(str, bool)
    png_exported = Signal(str)
    log_message = Signal(str)
    plan_executed = Signal(str, bool)


_instance: EventBus | None = None


def get_event_bus() -> EventBus:
    global _instance
    if _instance is None:
        _instance = EventBus()
    return _instance
