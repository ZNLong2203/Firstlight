"""What people are told, in Vietnamese for the farm and in plain English for tickets.

Times are on the farm clock, which is what the person reading the message lives by.
"""

from datetime import datetime, timedelta
from typing import Any


def clock(ts: datetime | None, offset_hours: float) -> str:
    if ts is None:
        return "vừa rồi"
    return (ts + timedelta(hours=offset_hours)).strftime("%H:%M")


def mg(value: float | None) -> str:
    return "?" if value is None else f"{value:.1f}".replace(".", ",")


def notify(
    target: str,
    incident: dict[str, Any],
    diagnosis: dict[str, Any],
    offset_hours: float,
    *,
    do_now: float | None = None,
    standby: str | None = None,
    minutes: float | None = None,
) -> str:
    cause = diagnosis.get("cause")
    at = clock(diagnosis.get("onset") or incident.get("opened_at"), offset_hours)
    pond, farm, gateway = incident.get("pond"), incident.get("farm"), incident.get("gateway")
    if cause == "aerator_failure":
        device = diagnosis.get("device") or "một quạt"
        if standby:
            return (
                f"Ao {pond}: quạt {device} ngừng quay lúc {at}. Firstlight đã bật quạt dự phòng {standby}. "
                f"Oxy hiện {mg(do_now)} mg/L. Sáng mai nhờ kiểm tra quạt hỏng."
            )
        margin = f", còn khoảng {round(minutes)} phút trước khi xuống 3 mg/L" if minutes else ""
        return (
            f"Ao {pond}: quạt {device} ngừng quay lúc {at} và không còn quạt dự phòng. "
            f"Oxy {mg(do_now)} mg/L{margin}. Cần ra ao ngay."
        )
    if cause == "power_outage":
        return (
            f"Trại {farm}: mất điện lúc {at}, mọi quạt đã dừng. Cần chạy máy phát: hãy duyệt trên Firstlight."
        )
    if cause == "gateway_offline":
        count = len(incident.get("ponds", []))
        return (
            f"Trại {farm}: mất tín hiệu bộ phát {gateway} từ {at}, không thấy {count} ao. "
            "Nhờ kỹ thuật kiểm tra nguồn và sóng 4G."
        )
    if cause == "ingest_regression":
        count = len(incident.get("ponds", []))
        release = diagnosis.get("release") or {}
        if release:
            back = f" Đề xuất: rollback về {release['previous']}." if release.get("previous") else ""
            version, onset = release["version"], diagnosis.get("onset")
            when = (
                f"trong lúc firstlight-api {version} được deploy"  # the data stopped with the restart
                if onset and release["started_at"] >= onset
                else f"ngay sau khi firstlight-api {version} được deploy lúc "
                f"{clock(release['started_at'], offset_hours)}"
            )
            return f"Firstlight không nhận được dữ liệu từ {count} ao từ {at}, {when}.{back}"
        return f"Firstlight không nhận được dữ liệu từ {count} ao từ {at}. Kiểm tra bản deploy gần nhất."
    return f"Ao {pond}: oxy {mg(do_now)} mg/L, chưa rõ nguyên nhân. Cần kiểm tra ao."


def ticket(target: str, device: str | None) -> str:
    if target == "repair_aerator":
        return f"Repair aerator {device}; switch the standby back off once it runs."
    if target == "clean_probe":
        return f"Clean and recalibrate DO probe {device}."
    return f"Check {device}."


ESCALATION = {
    "command_failed": "lệnh tới thiết bị không thực hiện được",
    "standby_idle": "quạt dự phòng đã bật nhưng không quay",
    "no_recovery": "oxy chưa hồi phục sau {minutes:g} phút",
}


def escalation(reason: str, incident: dict[str, Any], minutes: float = 0) -> str:
    where = f"ao {incident['pond']}" if incident.get("pond") else f"trại {incident.get('farm')}"
    return f"Cần người ra {where}: {ESCALATION[reason].format(minutes=minutes)}."
