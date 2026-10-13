"""Check the public Victoria Tennishal booking embed and email new openings."""

import json
import os
import smtplib
import ssl
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
API = "https://api.movitsport.com/v1"
EMBED_ID = 7
SECTION_ID = 9


def get_json(path, params=None):
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "VictoriaCourtAvailability/1.0"},
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.load(response)


def local_datetime(value, day):
    if isinstance(value, dict):
        value = value.get("start") or value.get("time") or value.get("value")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo:
            return parsed.astimezone(ZoneInfo("Europe/Amsterdam")).replace(tzinfo=None)
        return parsed
    except ValueError:
        pass
    try:
        return datetime.combine(day, time.fromisoformat(value))
    except ValueError:
        return None


def wanted_starts(day, config):
    if day.weekday() < 5:
        return [datetime.combine(day, time.fromisoformat(s)) for s in config["weekday_start_times"]]
    window = config["weekend_window"]
    cursor = datetime.combine(day, time.fromisoformat(window["start"]))
    end = datetime.combine(day, time.fromisoformat(window["end"]))
    duration = timedelta(minutes=config["duration_minutes"])
    result = []
    while cursor + duration <= end:
        result.append(cursor)
        cursor += timedelta(minutes=window["step_minutes"])
    return result


def allowed_by_embed(slot, start, day):
    """Respect booking starts supplied by the embed when present."""
    starts = slot.get("includedStartTimes")
    if starts is None:
        return True
    if not isinstance(starts, list):
        return False
    parsed = {item for raw in starts if (item := local_datetime(raw, day)) is not None}
    return start in parsed if parsed else False


def resource_names(items):
    result = {}
    for item in items:
        court = item.get("court", item)
        if isinstance(court, dict) and court.get("id") is not None:
            result[str(court["id"])] = court.get("name") or f"场地 {court['id']}"
    return result


def available_courts(day, slots, names, config):
    parsed = {}
    for slot in slots:
        if not isinstance(slot, dict) or slot.get("resourceId") is None:
            continue
        start = local_datetime(slot.get("start"), day)
        end = local_datetime(slot.get("end"), day)
        if start and end and start.date() == day:
            parsed[(str(slot["resourceId"]), start)] = (end, slot)

    duration = timedelta(minutes=config["duration_minutes"])
    matches = []
    for start in wanted_starts(day, config):
        for (resource_id, slot_start), (slot_end, first) in parsed.items():
            if slot_start != start or not allowed_by_embed(first, start, day):
                continue
            if first.get("maxTimeslotsInBooking") is not None:
                if int(first["maxTimeslotsInBooking"]) * 30 < config["duration_minutes"]:
                    continue
            cursor = slot_end
            while cursor < start + duration:
                next_slot = parsed.get((resource_id, cursor))
                if not next_slot or next_slot[0] <= cursor:
                    break
                cursor = next_slot[0]
            if cursor >= start + duration:
                matches.append({
                    "key": f"{day.isoformat()}|{start:%H:%M}|{resource_id}",
                    "day": day.isoformat(),
                    "start": start.strftime("%H:%M"),
                    "end": (start + duration).strftime("%H:%M"),
                    "court": names.get(resource_id, f"场地 {resource_id}"),
                })
    return matches


def send_email(config, matches):
    password = os.environ.get("QQ_SMTP_PASSWORD")
    sender = os.environ.get("SMTP_SENDER") or config["recipient_email"]
    if not password:
        raise RuntimeError("缺少 GitHub Actions secret: QQ_SMTP_PASSWORD")
    weekdays = "一二三四五六日"
    lines = [
        f"{m['day']}（周{weekdays[date.fromisoformat(m['day']).weekday()]}） "
        f"{m['start']}–{m['end']}  {m['court']}"
        for m in matches
    ]
    message = EmailMessage()
    message["From"] = sender
    message["To"] = config["recipient_email"]
    if matches:
        message["Subject"] = f"Victoria 网球场有 {len(matches)} 个符合条件的空档"
        message.set_content(
            "发现可预订的完整 60 分钟室内场地（荷兰当地时间）：\n\n"
            + "\n".join(lines)
            + "\n\n请尽快到 https://www.tv-victoria.nl/ 核实并预订。空档可能随时变化。"
        )
    else:
        message["Subject"] = "Victoria 网球场监控：测试邮件"
        message.set_content("这是一封邮件配置测试邮件，不代表发现可预订的场地。")
    with smtplib.SMTP_SSL("smtp.qq.com", 465, context=ssl.create_default_context(), timeout=30) as smtp:
        smtp.login(sender, password)
        smtp.send_message(message)


def main():
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    if "--test-email" in sys.argv:
        send_email(config, [])
        print("测试邮件已发送。")
        return
    embed = get_json(f"/embed/{EMBED_ID}")
    if SECTION_ID not in [int(value) for value in embed.get("sectionIds", [])]:
        raise RuntimeError("预约组件的场地区域已改变，需要更新监控配置")
    names = resource_names(get_json("/resource", {"section_id": SECTION_ID}))
    if not names:
        raise RuntimeError("场地编号接口没有返回场地，停止通知以免误报")

    today = datetime.now(ZoneInfo(config["timezone"])).date()
    matches = []
    for offset in range(config["lookahead_days"]):
        day = today + timedelta(days=offset)
        slots = get_json(
            f"/section/{SECTION_ID}/time_slots",
            {"date": day.isoformat(), "contexts": "[1]", "embed_id": EMBED_ID},
        )
        if not isinstance(slots, list):
            raise RuntimeError(f"{day}: 时间段接口返回了意外数据")
        matches.extend(available_courts(day, slots, names, config))

    state_file = ROOT / "sent.json"
    sent = set(json.loads(state_file.read_text(encoding="utf-8"))) if state_file.exists() else set()
    fresh = [item for item in matches if item["key"] not in sent]
    print(f"检查 {config['lookahead_days']} 天；符合条件 {len(matches)} 个；新空档 {len(fresh)} 个。")
    if fresh:
        send_email(config, fresh)
        sent.update(item["key"] for item in fresh)
        state_file.write_text(json.dumps(sorted(sent), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"已发送邮件并记录 {len(fresh)} 个空档。")


if __name__ == "__main__":
    main()
