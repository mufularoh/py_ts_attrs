from typing import Optional
from datetime import datetime, date
import re

current_year = datetime.now().year

def format_date(input_date: date, show_time: bool = False, skip_current_year: bool = False) -> str:
    def fix_day_month(v):
        if v[0] == '0':
            return v[1:]
        return v
    if not skip_current_year or input_date.year != current_year:
        ret = "{month}/{day}/{year}".format(
            month=fix_day_month(input_date.strftime("%m")),
            day=fix_day_month(input_date.strftime("%d")),
            year=input_date.strftime("%y")
        )
    else:
        ret = "{month}/{day}".format(
            month=fix_day_month(input_date.strftime("%m")),
            day=fix_day_month(input_date.strftime("%d"))
        )
    if show_time:
        ret += " " + input_date.strftime("%H:%M")
    return ret


PARSE_DATE_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{1,2})$")
PARSE_DATETIME_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{1,2}) (\d{1,2}):(\d{1,2})$")

def parse_date(formatted_value: str, with_time: bool = False) -> Optional[date]:
    if with_time:
        match = PARSE_DATETIME_RE.findall(formatted_value)
        if not match:
            return None
        return datetime(int("20" + match[0][2]), int(match[0][0]), int(match[0][1]), int(match[0][3]), int(match[0][4]))
    else:
        match = PARSE_DATE_RE.findall(formatted_value)
        if not match:
            return None
        return date(int("20" + match[0][2]), int(match[0][0]), int(match[0][1]))
