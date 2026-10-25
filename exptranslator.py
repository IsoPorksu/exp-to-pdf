import json
import os
import winreg
lazy from pathlib import Path
lazy from xml.sax.saxutils import escape

lazy from reportlab.lib.pagesizes import A4
lazy from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak,
    Flowable,
)
lazy from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
lazy from reportlab.lib import colors
lazy from reportlab.lib.units import mm
lazy from reportlab.pdfbase.pdfmetrics import stringWidth
lazy from reportlab.pdfbase import pdfmetrics
lazy from reportlab.pdfbase.ttfonts import TTFont, TTFError
lazy from reportlab.pdfgen.canvas import Canvas
import pandas as pd

CONFIG_FILE_NAME = ""
while not CONFIG_FILE_NAME:
    CONFIG_FILE_NAME = input("Please type the file name of the config file (e.g. \"config_11_13_9.11.2026.json\") / Ole hyvä ja kirjoita asetustiedoston nimi (esim. \"config_11_13_9.11.2026.json\"): ")

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config-files" / CONFIG_FILE_NAME

# Display settings
pd.set_option("display.max_rows", None)
pd.set_option("display.max_columns", None)
pd.set_option("display.width", 1000)


class PageColorMarker(Flowable):
    def __init__(self, page_color, day_type, page_state):
        super().__init__()
        self.page_color = page_color
        self.day_type = day_type
        self.page_state = page_state
        self.width = 0
        self.height = 0

    def draw(self):
        self.page_state["color"] = self.page_color
        self.page_state["day_type"] = self.day_type


class PageMetadataCanvas(Canvas):
    def __init__(self, *args, page_state, draw_page_chrome, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []
        self._page_state = page_state
        self._draw_page_chrome = draw_page_chrome

    def showPage(self):
        self._saved_page_states.append(
            (dict(self.__dict__), dict(self._page_state))
        )
        self._startPage()

    def save(self):
        for page_number, (page_state, metadata) in enumerate(
            self._saved_page_states, start=1
        ):
            self.__dict__.update(page_state)
            page_contents = self._code
            self._code = []
            self._draw_page_chrome(self, page_number, metadata)
            self._code.extend(page_contents)
            super().showPage()
        super().save()


def load_config(filepath):
    with open(filepath, "r", encoding="utf-8") as config_file:
        config = json.load(config_file)

    if not isinstance(config.get("font_name"), str) or not config["font_name"]:
        raise ValueError("Configuration must contain a non-empty 'font_name'.")
    if not isinstance(config.get("font_size"), (int, float)) or config["font_size"] <= 0:
        raise ValueError("'font_size' must be a positive number.")
    if not isinstance(config.get("routes"), list) or not config["routes"]:
        raise ValueError("Configuration must contain a non-empty 'routes' list.")
    if not isinstance(config.get("file_format"), str) or not config["file_format"]:
        raise ValueError("Configuration must contain a recognised file_format.")
    if not isinstance(config.get("day_types"), list) or not config["day_types"]:
        raise ValueError("Configuration must contain a non-empty 'day_types' list.")

    for route in config["routes"]:
        for key in ("name", "route_shape", "pivot_stop"):
            if key not in route:
                raise ValueError(f"Route configuration is missing '{key}': {route}")
        if not isinstance(route["name"], str) or not isinstance(route["pivot_stop"], str):
            raise ValueError(f"Route name and pivot_stop must be strings: {route}")
        if (
            not isinstance(route["route_shape"], list)
            or not route["route_shape"]
            or not all(isinstance(stop, str) for stop in route["route_shape"])
        ):
            raise ValueError(f"Route '{route['name']}' has an empty route_shape.")
        if not isinstance(route.get("stop_labels", {}), dict):
            raise ValueError(f"Route '{route['name']}' stop_labels must be an object.")

    for day_type in config["day_types"]:
        for key in ("name", "exp_file"):
            if key not in day_type:
                raise ValueError(
                    f"Day type configuration is missing '{key}': {day_type}"
                )
        if not isinstance(day_type["name"], str) or not isinstance(day_type["exp_file"], str):
            raise ValueError(f"Day type name and exp_file must be strings: {day_type}")
        try:
            colors.toColor(day_type.get("page_color", "#FFFFFF"))
        except ValueError as error:
            raise ValueError(
                f"Invalid page_color for day type '{day_type['name']}'."
            ) from error

    for key in ("page_header", "page_footer"):
        if key in config and not isinstance(config[key], str):
            raise ValueError(f"'{key}' must be a string.")

    return config


def register_system_font(font_name):
    if font_name in pdfmetrics.getRegisteredFontNames():
        return pdfmetrics.getFont(font_name)

    font_roots = [
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Microsoft"
        / "Windows"
        / "Fonts",
    ]
    font_aliases = {}
    for root in font_roots:
        if root.is_dir():
            for extension in ("*.ttf", "*.otf"):
                for font_path in root.rglob(extension):
                    font_aliases.setdefault(font_path.resolve(), set())

    registry_keys = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
    )
    for hive, key_path in registry_keys:
        try:
            key = winreg.OpenKey(hive, key_path)
        except FileNotFoundError:
            continue
        with key:
            value_count = winreg.QueryInfoKey(key)[1]
            for index in range(value_count):
                alias, value, _ = winreg.EnumValue(key, index)
                font_path = Path(os.path.expandvars(value))
                candidates = (
                    [font_path]
                    if font_path.is_absolute()
                    else [root / font_path.name for root in font_roots]
                )
                for candidate in candidates:
                    if candidate.is_file():
                        font_aliases.setdefault(candidate.resolve(), set()).add(
                            alias.rsplit("(", 1)[0].strip()
                        )
                        break

    requested_name = font_name.casefold()
    unsupported_match = None

    for font_path, aliases in sorted(font_aliases.items()):
        try:
            font = TTFont(font_name, str(font_path))
        except TTFError as error:
            if requested_name in {
                font_path.stem.casefold(),
                *(alias.casefold() for alias in aliases),
            }:
                unsupported_match = (font_path, error)
            continue

        family_name = font.face.familyName
        face_name = font.face.name
        if isinstance(family_name, bytes):
            family_name = family_name.decode("latin-1")
        if isinstance(face_name, bytes):
            face_name = face_name.decode("latin-1")
        if requested_name not in {
            str(family_name).casefold(),
            str(face_name).casefold(),
            font_path.stem.casefold(),
            *(alias.casefold() for alias in aliases),
        }:
            continue

        pdfmetrics.registerFont(font)
        return font

    if unsupported_match:
        path, error = unsupported_match
        raise ValueError(
            f"Installed font '{font_name}' cannot be loaded by ReportLab "
            f"({path}): {error}"
        ) from error

    roots = ", ".join(str(root) for root in font_roots)
    raise ValueError(
        f"Installed TrueType font '{font_name}' was not found in: {roots}"
    )


def normalize_time(t_str):
    """Pads single-digit hours with a leading zero (e.g., '4:27' -> '04:27')."""
    if not t_str or not isinstance(t_str, str) or ":" not in t_str:
        return t_str
    parts = t_str.split(":")
    try:
        if len(parts) >= 2 and parts[0].isdigit():
            return f"{int(parts[0]):02d}:{parts[1]}"
    except ValueError:
        pass
    return t_str


def time_to_min(t_str):
    """Converts HH:MM or HH:MM:SS to minutes past midnight safely."""
    if not t_str or not isinstance(t_str, str):
        return -1
    parts = t_str.split(":")
    try:
        if len(parts) >= 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 1 and parts[0].isdigit():
            return int(parts[0]) * 60
    except ValueError:
        return -1
    return -1


def parse_exp_file(filepath, config):
    blocks = []
    current_block = None
    current_trip = None

    with open(filepath, "r", encoding="cp1252") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            parts = line.split(";")
            record_type = parts[0]

            if config["file_format"] == "tram":
                if record_type == "block":
                    current_block = {
                        "block_id": parts[1],
                        "vehicle_type": parts[2],
                        "trips": [],
                    }
                    blocks.append(current_block)

                elif record_type == "trip":
                    current_trip = {
                        "trip_id": parts[1],
                        "start_stop": parts[2],
                        "end_stop": parts[3],
                        "line_number": parts[4] if len(parts) > 4 else "",
                        "start_time": normalize_time(parts[7]),
                        "end_time": normalize_time(parts[8]),
                        "timing_points": [],
                    }
                    if current_block:
                        current_block["trips"].append(current_trip)

                elif record_type == "triptp":
                    if current_trip:
                        tp = {
                            "stop_name": parts[1],
                            "time": normalize_time(parts[2]),
                        }
                        current_trip["timing_points"].append(tp)

            elif config["file_format"] == "bus_tender":
                if record_type == "vuoro":
                    current_block = {
                        "block_id": parts[1],
                        "vehicle_type": parts[2],
                        "trips": [],
                    }
                    blocks.append(current_block)

                elif record_type == "lähtö":
                    current_trip = {
                        "trip_id": parts[1],
                        "start_stop": parts[2],
                        "end_stop": parts[3],
                        "line_number": parts[4] if len(parts) > 4 else "",
                        "start_time": normalize_time(parts[7]),
                        "end_time": normalize_time(parts[8]),
                        "timing_points": [],
                    }
                    if current_block:
                        current_block["trips"].append(current_trip)

                elif record_type == "pysäkki":
                    if current_trip:
                        tp = {
                            "stop_name": parts[1],
                            "time": normalize_time(parts[5]),
                        }
                        current_trip["timing_points"].append(tp)

    return blocks


def combine_block_trips(blocks):
    """Combines consecutive trips where Trip A end_stop/end_time == Trip B start_stop/start_time."""
    combined_blocks = []
    for block in blocks:
        trips = block["trips"]
        if not trips:
            combined_blocks.append(block)
            continue

        new_trips = []
        i = 0
        while i < len(trips):
            current_trip = trips[i].copy()

            while i + 1 < len(trips):
                next_trip = trips[i + 1]
                if (
                    current_trip["end_stop"] == next_trip["start_stop"]
                    and current_trip["end_time"] == next_trip["start_time"]
                ):
                    current_trip["end_stop"] = next_trip["end_stop"]
                    current_trip["end_time"] = next_trip["end_time"]

                    tps_a = current_trip["timing_points"]
                    tps_b = next_trip["timing_points"]
                    if (
                        tps_a
                        and tps_b
                        and tps_a[-1]["stop_name"] == tps_b[0]["stop_name"]
                        and tps_a[-1]["time"] == tps_b[0]["time"]
                    ):
                        current_trip["timing_points"] = tps_a + tps_b[1:]
                    else:
                        current_trip["timing_points"] = tps_a + tps_b
                    i += 1
                else:
                    break
            new_trips.append(current_trip)
            i += 1

        combined_blocks.append({
            "block_id": block["block_id"],
            "vehicle_type": block["vehicle_type"],
            "trips": new_trips,
        })
    return combined_blocks


def trip_matches_patterns(trip, patterns):
    """Checks if a trip contains at least one of the defined patterns in exact order."""
    if not patterns:
        return True

    trip_stops = [tp["stop_name"] for tp in trip["timing_points"]]

    for pattern in patterns:
        p_len = len(pattern)
        for j in range(len(trip_stops) - p_len + 1):
            if trip_stops[j : j + p_len] == pattern:
                return True
    return False


def map_trip_to_shape(trip, route_shape, pivot_stop, force_half=None):
    trip_tps = trip["timing_points"]
    if len(trip_tps) < 2:
        return None, 0

    pivot_indices = [i for i, s in enumerate(route_shape) if s == pivot_stop]
    has_two_pivot_stops = len(pivot_indices) >= 2
    second_pivot = (
        pivot_indices[1] if has_two_pivot_stops else len(route_shape)
    )

    mapping = {}
    last_time_val = -1

    if not has_two_pivot_stops:
        allowed_range = range(len(route_shape))
    elif force_half == "pre":
        allowed_range = range(0, second_pivot)
    elif force_half == "post":
        allowed_range = range(second_pivot, len(route_shape))
    else:
        allowed_range = range(len(route_shape))

    shape_idx = allowed_range.start

    for tp in trip_tps:
        raw_stop = tp["stop_name"]
        t_val = time_to_min(tp["time"])

        target_stop = raw_stop
        matching_shape_stops = [
            route_shape[idx]
            for idx in allowed_range
            if route_shape[idx] == raw_stop or route_shape[idx].startswith(raw_stop)
        ]

        if matching_shape_stops:
            target_stop = matching_shape_stops[0]

        matched = False
        while shape_idx < allowed_range.stop:
            if route_shape[shape_idx] == target_stop and t_val >= last_time_val:
                mapping[shape_idx] = tp["time"]
                last_time_val = t_val
                shape_idx += 1
                matched = True
                break
            shape_idx += 1

        if not matched:
            for s_idx in allowed_range:
                if route_shape[s_idx] == target_stop and s_idx not in mapping:
                    mapping[s_idx] = tp["time"]
                    matched = True
                    break

    matching_stops_count = len(mapping)
    if matching_stops_count < 2:
        return None, matching_stops_count

    return mapping, matching_stops_count


def generate_timetable(blocks, config):
    route_shape = config["route_shape"]
    pivot_stop = config["pivot_stop"]
    match_patterns = config.get("match_patterns", [])

    pivot_indices = [i for i, stop in enumerate(route_shape) if stop == pivot_stop]
    has_two_pivot_stops = len(pivot_indices) >= 2
    second_pivot_idx = (
        pivot_indices[1] if has_two_pivot_stops else len(route_shape)
    )

    formatted_trips = []

    for block in blocks:
        block_id = block["block_id"]
        for trip_idx, trip in enumerate(block["trips"]):
            if not trip_matches_patterns(trip, match_patterns):
                continue

            if has_two_pivot_stops:
                m_pre, c_pre = map_trip_to_shape(
                    trip, route_shape, pivot_stop, force_half="pre"
                )
                m_post, c_post = map_trip_to_shape(
                    trip, route_shape, pivot_stop, force_half="post"
                )

                mapping = None
                count = 0
                is_post_pivot = False

                if trip["start_stop"] == pivot_stop and c_post >= 2:
                    mapping = m_post
                    count = c_post
                    is_post_pivot = True
                elif c_post > c_pre and c_post >= 2:
                    mapping = m_post
                    count = c_post
                    is_post_pivot = True
                elif c_pre >= 2:
                    mapping = m_pre
                    count = c_pre
                    is_post_pivot = False
                else:
                    mapping, count = map_trip_to_shape(
                        trip, route_shape, pivot_stop
                    )
                    if mapping:
                        is_post_pivot = any(
                            idx >= second_pivot_idx for idx in mapping.keys()
                        )
            else:
                mapping, count = map_trip_to_shape(
                    trip, route_shape, pivot_stop
                )
                is_post_pivot = False

            if count >= 2 and mapping:
                following_trip = (
                    block["trips"][trip_idx + 1]
                    if trip_idx + 1 < len(block["trips"])
                    else None
                )
                formatted_trips.append({
                    "block_id": block_id,
                    "trip_obj": trip,
                    "trip_idx": trip_idx,
                    "mapping": mapping,
                    "start_time": trip["start_time"],
                    "end_time": trip["end_time"],
                    "is_post_pivot": is_post_pivot,
                    "following_line_number": (
                        following_trip.get("line_number", "")
                        if following_trip
                        else ""
                    ),
                })

    rows = []
    used_pre_pivot_ft_ids = set()

    MIN_LAYOVER_MINUTES = -15
    MAX_LAYOVER_MINUTES = 180

    for ft in formatted_trips:
        if ft["is_post_pivot"] and ft.get("mapping"):
            row = {"Block": ft["block_id"]}
            row["Linjalle"] = (
                f"→ L{ft['following_line_number']}"
                if config.get("show_following_line")
                and ft["following_line_number"]
                else ""
            )
            for idx, t_val in ft["mapping"].items():
                row[idx] = t_val

            current_block_id = ft["block_id"]
            current_trip_start_min = time_to_min(ft["start_time"])

            pre_candidates = [
                c
                for c in formatted_trips
                if c["block_id"] == current_block_id
                and c["trip_idx"] < ft["trip_idx"]
                and not c["is_post_pivot"]
                and id(c) not in used_pre_pivot_ft_ids
            ]

            best_prev_ft = None
            min_time_diff = float("inf")

            for candidate in pre_candidates:
                cand_end_min = time_to_min(candidate["end_time"])
                diff = current_trip_start_min - cand_end_min

                if MIN_LAYOVER_MINUTES <= diff <= MAX_LAYOVER_MINUTES:
                    if diff < min_time_diff:
                        min_time_diff = diff
                        best_prev_ft = candidate

            if best_prev_ft and best_prev_ft.get("mapping"):
                used_pre_pivot_ft_ids.add(id(best_prev_ft))
                for idx, t_val in best_prev_ft["mapping"].items():
                    if idx not in row:
                        row[idx] = t_val

            rows.append(row)

    for ft in formatted_trips:
        if (
            not ft["is_post_pivot"]
            and id(ft) not in used_pre_pivot_ft_ids
            and ft.get("mapping")
        ):
            row = {"Block": ft["block_id"]}
            row["Linjalle"] = (
                f"→ L{ft['following_line_number']}"
                if config.get("show_following_line")
                and ft["following_line_number"]
                else ""
            )
            for idx, t_val in ft["mapping"].items():
                row[idx] = t_val
            rows.append(row)

    if not rows:
        return pd.DataFrame()

    # --- CUSTOM CHRONOLOGICAL SORTING ALGORITHM ---
    def is_row_later(row_existing, row_new):
        """Compares row_existing and row_new stop-by-stop along route_shape.

        Returns True if row_existing is chronologically later than row_new.
        Blank spaces are neutral.
        """
        for i in range(len(route_shape)):
            t_exist = time_to_min(row_existing.get(i, ""))
            t_new = time_to_min(row_new.get(i, ""))

            if t_exist >= 0 and t_new >= 0:
                if t_exist > t_new:
                    return True
                elif t_exist < t_new:
                    return False
                # If equal, continue to the next stop
        return False

    sorted_rows = [rows[0]]
    for new_row in rows[1:]:
        inserted = False
        for k in range(len(sorted_rows)):
            if is_row_later(sorted_rows[k], new_row):
                sorted_rows.insert(k, new_row)
                inserted = True
                break
        if not inserted:
            sorted_rows.append(new_row)

    rows = sorted_rows

    table_data = []
    for r in rows:
        row_dict = {"Block": r.get("Block", "")}
        for i in range(len(route_shape)):
            row_dict[i] = r.get(i, "")
        table_data.append(row_dict)

    df_sorted = pd.DataFrame(table_data)
    stop_labels = config.get("stop_labels", {})
    df_sorted.columns = ["Block"] + [
        stop_labels.get(stop, stop) for stop in route_shape
    ]
    if config.get("show_following_line"):
        df_sorted["Linjalle"] = [
            row.get("Linjalle", "") for row in rows
        ]

    return df_sorted


def export_timetables_to_pdf(day_timetables, config, filename):
    font_name = config["font_name"]
    font_size = float(config["font_size"])
    font = register_system_font(font_name)
    digit_widths = {
        stringWidth(str(digit), font_name, font_size)
        for digit in range(10)
    }
    if max(digit_widths) - min(digit_widths) > 0.01:
        raise ValueError(
            f"Font '{font_name}' does not use tabular numerals by default; "
            "choose a font with equal-width digits."
        )
    required_characters = {"→"}
    for _, route_timetables, _ in day_timetables:
        for route_name, dataframe, route_config in route_timetables:
            required_characters.update(route_name)
            stop_labels = route_config.get("stop_labels", {})
            required_characters.update(
                character
                for stop in route_config["route_shape"]
                for character in stop_labels.get(stop, stop)
            )
            if route_config.get("show_following_line"):
                required_characters.update("Linjalle")
                required_characters.add(" ")
            for value in dataframe.to_numpy().flatten():
                if not pd.isna(value):
                    required_characters.update(str(value))
    for day_type_name, _, _ in day_timetables:
        required_characters.update(day_type_name)
    required_characters.update(config.get("page_header", ""))
    required_characters.update(config.get("page_footer", ""))
    missing_characters = sorted(
        character
        for character in required_characters
        if not character.isspace() and ord(character) not in font.face.charWidths
    )
    if missing_characters:
        raise ValueError(
            f"Font '{font_name}' does not support required characters: "
            + "".join(missing_characters)
        )

    margin_left = 10 * mm
    margin_right = 10 * mm
    usable_width = A4[0] - margin_left - margin_right
    cell_padding = 1.5
    vertical_cell_padding = 1.0
    page_state = {"color": colors.white, "day_type": ""}

    def draw_page_chrome(canvas, page_number, metadata):
        canvas.saveState()
        canvas.setFillColor(metadata["color"])
        canvas.rect(0, 0, *canvas._pagesize, stroke=0, fill=1)
        canvas.setFillColor(colors.black)
        canvas.setFont(font_name, font_size)
        replacements = {
            "page": page_number,
            "day_type": metadata["day_type"],
        }
        header = config.get("page_header", "").format_map(replacements)
        footer = config.get("page_footer", "").format_map(replacements)
        if header:
            canvas.drawString(margin_left, A4[1] - 5 * mm, header)
        if footer:
            canvas.drawString(margin_left, 5 * mm, footer)
        canvas.restoreState()

    doc = SimpleDocTemplate(
        filename,
        pagesize=A4,
        rightMargin=margin_right,
        leftMargin=margin_left,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title="Raitioliikenteen aikataulu",
    )

    styles = getSampleStyleSheet()
    day_title_style = ParagraphStyle(
        "DayTypeTitle",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=font_size + 2,
        leading=font_size + 3,
        alignment=0,
        textColor=colors.black,
        spaceAfter=2 * mm,
    )
    route_title_style = ParagraphStyle(
        "RouteTitle",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=font_size + 1,
        leading=font_size + 2,
        alignment=0,
        textColor=colors.black,
        spaceAfter=2 * mm,
    )
    header_style = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=font_size,
        leading=font_size + 1,
        alignment=1,
        wordWrap="CJK",
        textColor=colors.black,
    )
    cell_style = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=font_size,
        leading=font_size + 1,
        alignment=1,
        wordWrap="CJK",
        textColor=colors.black,
    )

    def get_column_widths(dataframe):
        headers = [
            "Vuoro" if column == "Block" else str(column)
            for column in dataframe.columns
        ]
        widths = []
        for column_index, header in enumerate(headers):
            widest = stringWidth(header, font_name, font_size)
            for value in dataframe.iloc[:, column_index]:
                if not pd.isna(value):
                    widest = max(
                        widest,
                        stringWidth(str(value), font_name, font_size),
                    )
            widths.append(widest + 2 * cell_padding)
        return widths

    def make_table(dataframe, route_config):
        headers = [
            "Vuoro" if column == "Block" else str(column)
            for column in dataframe.columns
        ]
        data = [[Paragraph(escape(header), header_style) for header in headers]]
        for _, row in dataframe.iterrows():
            data.append([
                Paragraph(escape(str(value)), cell_style)
                if not pd.isna(value) and str(value)
                else ""
                for value in row
            ])

        table = Table(
            data,
            colWidths=get_column_widths(dataframe),
            repeatRows=1,
            hAlign="LEFT",
            spaceBefore=0,
            spaceAfter=0,
        )
        table_style = [
            ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
            ("FONTNAME", (0, 0), (-1, -1), font_name),
            ("FONTSIZE", (0, 0), (-1, -1), font_size),
            ("LEADING", (0, 0), (-1, -1), font_size + 1),
            ("LEFTPADDING", (0, 0), (-1, -1), cell_padding),
            ("RIGHTPADDING", (0, 0), (-1, -1), cell_padding),
            ("TOPPADDING", (0, 0), (-1, -1), vertical_cell_padding),
            ("BOTTOMPADDING", (0, 0), (-1, -1), vertical_cell_padding),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.7, colors.black),
            ("LINEAFTER", (0, 0), (0, -1), 0.7, colors.black),
        ]

        for row_idx in range(3, len(data), 3):
            table_style.append(
                ("LINEBELOW", (0, row_idx), (-1, row_idx), 0.35, colors.black)
            )
        for row_start in range(1, len(data), 3):
            table_style.append(
                (
                    "NOSPLIT",
                    (0, row_start),
                    (-1, min(row_start + 2, len(data) - 1)),
                )
            )

        route_shape = route_config["route_shape"]
        pivot_columns = [
            index + 1
            for index, stop in enumerate(route_shape)
            if stop == route_config["pivot_stop"]
        ]
        if len(pivot_columns) >= 2:
            table_style.append(
                (
                    "LINEBEFORE",
                    (pivot_columns[1], 0),
                    (pivot_columns[1], -1),
                    0.7,
                    colors.black,
                )
            )

        last_stop_column = len(route_shape)
        table_style.append(
            (
                "LINEAFTER",
                (last_stop_column, 0),
                (last_stop_column, -1),
                0.7,
                colors.black,
            )
        )

        shaded_stops = set(route_config.get("shaded_stops", []))
        for column, stop in enumerate(route_shape, start=1):
            if stop in shaded_stops:
                table_style.append(
                    (
                        "BACKGROUND",
                        (column, 0),
                        (column, -1),
                        colors.HexColor("#D0D0D0"),
                    )
                )

        table.setStyle(TableStyle(table_style))
        return table

    def make_side_by_side_table(
        route_name,
        dataframe,
        route_config,
        next_name,
        next_dataframe,
        next_config,
        gap_width,
    ):
        left_widths = get_column_widths(dataframe)
        right_widths = get_column_widths(next_dataframe)
        gap_column = len(left_widths)
        right_offset = gap_column + 1
        title_row = [
            Paragraph(escape(route_name), route_title_style),
            *("" for _ in left_widths[1:]),
            "",
            Paragraph(escape(next_name), route_title_style),
            *("" for _ in right_widths[1:]),
        ]
        header_row = [
            "",
        ] * (len(left_widths) + 1 + len(right_widths))
        for offset, frame in ((0, dataframe), (right_offset, next_dataframe)):
            for index, column in enumerate(frame.columns):
                label = "Vuoro" if column == "Block" else str(column)
                header_row[offset + index] = Paragraph(
                    escape(label), header_style
                )
        data = [title_row, header_row]

        row_count = max(len(dataframe), len(next_dataframe))
        for row_index in range(row_count):
            row = []
            for frame, widths in (
                (dataframe, left_widths),
                (next_dataframe, right_widths),
            ):
                if row_index < len(frame):
                    row.extend(
                        Paragraph(escape(str(value)), cell_style)
                        if not pd.isna(value) and str(value)
                        else ""
                        for value in frame.iloc[row_index]
                    )
                else:
                    row.extend("" for _ in widths)
                if frame is dataframe:
                    row.append("")
            data.append(row)

        table_style = [
            ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
            ("FONTNAME", (0, 0), (-1, -1), font_name),
            ("FONTSIZE", (0, 0), (-1, -1), font_size),
            ("LEADING", (0, 0), (-1, -1), font_size + 1),
            ("LEFTPADDING", (0, 0), (-1, -1), cell_padding),
            ("RIGHTPADDING", (0, 0), (-1, -1), cell_padding),
            ("TOPPADDING", (0, 0), (-1, -1), vertical_cell_padding),
            ("BOTTOMPADDING", (0, 0), (-1, -1), vertical_cell_padding),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("SPAN", (0, 0), (gap_column - 1, 0)),
            ("SPAN", (right_offset, 0), (-1, 0)),
        ]
        for offset, frame, route in (
            (0, dataframe, route_config),
            (right_offset, next_dataframe, next_config),
        ):
            width_count = len(frame.columns)
            table_style.append(
                (
                    "LINEBELOW",
                    (offset, 1),
                    (offset + width_count - 1, 1),
                    0.7,
                    colors.black,
                )
            )
            table_style.append(
                ("LINEAFTER", (offset, 1), (offset, -1), 0.7, colors.black)
            )
            route_shape = route["route_shape"]
            pivot_columns = [
                offset + index + 1
                for index, stop in enumerate(route_shape)
                if stop == route["pivot_stop"]
            ]
            if len(pivot_columns) >= 2:
                table_style.append(
                    (
                        "LINEBEFORE",
                        (pivot_columns[1], 1),
                        (pivot_columns[1], -1),
                        0.7,
                        colors.black,
                    )
                )
            table_style.append(
                (
                    "LINEAFTER",
                    (offset + len(route_shape), 1),
                    (offset + len(route_shape), -1),
                    0.7,
                    colors.black,
                )
            )
            for column, stop in enumerate(route_shape, start=offset + 1):
                if stop in set(route.get("shaded_stops", [])):
                    table_style.append(
                        (
                            "BACKGROUND",
                            (column, 1),
                            (column, -1),
                            colors.HexColor("#D0D0D0"),
                        )
                    )

        for row_start in range(2, len(data), 3):
            row_end = min(row_start + 2, len(data) - 1)
            table_style.append(
                ("NOSPLIT", (0, row_start), (-1, row_end))
            )
            if row_end < len(data) - 1:
                table_style.append(
                    ("LINEBELOW", (0, row_end), (-1, row_end), 0.35, colors.black)
                )

        return Table(
            data,
            colWidths=left_widths + [gap_width] + right_widths,
            repeatRows=2,
            hAlign="LEFT",
            style=TableStyle(table_style),
        )

    def append_route(elements, route_name, dataframe, route_config):
        if dataframe.empty:
            print(f"No timetable data for {route_name}; section omitted.")
            return
        table = make_table(dataframe, route_config)
        title_table = Table(
            [[Paragraph(escape(route_name), route_title_style)]],
            colWidths=[sum(get_column_widths(dataframe))],
            hAlign="LEFT",
            style=TableStyle([
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]),
        )
        elements.extend([
            title_table,
            Spacer(1, 1 * mm),
            table,
            Spacer(1, 5 * mm),
        ])

    elements = []
    for day_index, (day_type_name, route_timetables, day_config) in enumerate(day_timetables):
        if day_index:
            elements.append(PageBreak())
        elements.extend([
            PageColorMarker(
                colors.toColor(day_config.get("page_color", "#FFFFFF")),
                day_type_name,
                page_state,
            ),
            Paragraph(escape(day_type_name), day_title_style),
            Spacer(1, 2 * mm),
        ])

        route_index = 0
        while route_index < len(route_timetables):
            route_name, dataframe, route_config = route_timetables[route_index]
            next_route = (
                route_timetables[route_index + 1]
                if route_index + 1 < len(route_timetables)
                else None
            )
            pair_name = route_config.get("side_by_side_with")

            if (
                pair_name
                and next_route is not None
                and next_route[0] == pair_name
                and not dataframe.empty
                and not next_route[1].empty
            ):
                next_name, next_dataframe, next_config = next_route
                gap_width = 4 * mm
                left_width = sum(get_column_widths(dataframe))
                right_width = sum(get_column_widths(next_dataframe))
                if left_width + gap_width + right_width <= usable_width:
                    elements.append(make_side_by_side_table(
                        route_name,
                        dataframe,
                        route_config,
                        next_name,
                        next_dataframe,
                        next_config,
                        gap_width,
                    ))
                    elements.append(Spacer(1, 5 * mm))
                else:
                    append_route(elements, route_name, dataframe, route_config)
                    append_route(elements, next_name, next_dataframe, next_config)
                route_index += 2
                continue

            append_route(elements, route_name, dataframe, route_config)
            route_index += 1

    doc.build(
        elements,
        canvasmaker=lambda *args, **kwargs: PageMetadataCanvas(
            *args,
            page_state=page_state,
            draw_page_chrome=draw_page_chrome,
            **kwargs,
        ),
    )
    print(f"PDF successfully generated: {filename}")

def main():
    config = load_config(CONFIG_PATH)
    register_system_font(config["font_name"])

    day_timetables = []
    for day_type in config["day_types"]:
        exp_path = Path(day_type["exp_file"])
        if not exp_path.is_absolute():
            exp_path = BASE_DIR / exp_path

        blocks = combine_block_trips(parse_exp_file(exp_path, config))
        route_timetables = []
        #print(f"\n================ {day_type['name']} ================")
        for route_config in config["routes"]:
            route_name = route_config["name"]
            timetable = generate_timetable(blocks, route_config)
            #print(f"\n--- {route_name} ---")
            #print(timetable.to_string(index=False))
            route_timetables.append((route_name, timetable, route_config))
        day_timetables.append((day_type["name"], route_timetables, day_type))

    output_path = Path(config.get("output_pdf", "timetable_report.pdf"))
    if not output_path.is_absolute():
        output_path = BASE_DIR / "output-pdfs" / output_path
    export_timetables_to_pdf(day_timetables, config, str(output_path))


if __name__ == "__main__":
    main()