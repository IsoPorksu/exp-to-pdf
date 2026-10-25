from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle,
    Paragraph, Spacer, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
import pandas as pd

# Display settings
pd.set_option("display.max_rows", None)
pd.set_option("display.max_columns", None)
pd.set_option("display.width", 1000)

file_name = "RAITIO_Hastus2017_1013_Ma-Pe_20261109_20270425.exp"

# --- MULTI-ROUTE CONFIGURATION ---
ROUTES = {
    "11/13": {
        "ROUTE_SHAPE": [
            "KRU",
            "HOP1",
            "ZOO1",
            "NIH1",
            "KLA12",
            "HÄM1",
            "MÄR1",  # Pre-pivot MÄR (Index 6)
            "PRA1",
            "LPA",  # Index 8: First occurrence (arrival / pre-pivot)
            "LPA",  # Index 9: Second occurrence (departure / post-pivot)
            "PRA2",
            "MÄR2",  # Post-pivot MÄR (Index 11)
            "HÄM2",
            "KLA22",
            "NIH2",
            "ZOO2",
            "HOP2",
            "KRU",
        ],
        "PIVOT_STOP": "LPA",
        "MATCH_PATTERNS": [["KLA12"], ["KLA22"]],
        "SHADED_STOPS": ["KLA12", "PRA1", "KLA22"],
    },
    "Hallista linjalle": {
        "ROUTE_SHAPE": [
            "RSV_PO",
            "RUS2",
            "TTP2",
            "EL2",
            "PRA2",
            "LPA",
        ],
        "PIVOT_STOP": "LPA",
        "SORT_INDICES": [3, 8],  # Fallback sort indices for routes without MÄR
        "MATCH_PATTERNS": [["RUS1"], ["RUS2"]],
        "SHADED_STOPS": ["PRA2", "LPA"],
        "SHOW_FOLLOWING_LINE": True,
    },
    "Linjasta halliin": {
        "ROUTE_SHAPE": [
            "LPA",
            "PRA1",
            "EL1",
            "TTP1",
            "RUS1",
            "RSV_PI",
        ],
        "PIVOT_STOP": "LPA",
        "SORT_INDICES": [3, 8],  # Fallback sort indices for routes without MÄR
        "MATCH_PATTERNS": [["RUS1"], ["RUS2"]],
        "SHADED_STOPS": ["PRA1", "LPA"],
    },
}


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


def parse_exp_file(filepath):
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

            if record_type == "block":
                current_block = {
                    "block_id": parts[1],
                    "network": parts[2],
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
                        "distance": parts[3] if len(parts) > 3 else None,
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
            "network": block["network"],
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

    for i, tp in enumerate(trip_tps):
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
    route_shape = config["ROUTE_SHAPE"]
    pivot_stop = config["PIVOT_STOP"]
    match_patterns = config.get("MATCH_PATTERNS", [])

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
                if config.get("SHOW_FOLLOWING_LINE")
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
                if config.get("SHOW_FOLLOWING_LINE")
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
    df_sorted.columns = ["Block"] + route_shape
    if config.get("SHOW_FOLLOWING_LINE"):
        df_sorted["Linjalle"] = [
            row.get("Linjalle", "") for row in rows
        ]

    return df_sorted


def export_timetables_to_pdf(route_timetables, filename="timetable_report.pdf"):
    """Export a compact, portrait A4 timetable in the reference's style."""

    # --- Page setup: portrait A4 ---
    margin_left = 12 * mm
    margin_right = 12 * mm
    margin_top = 9 * mm
    margin_bottom = 8 * mm

    doc = SimpleDocTemplate(
        filename,
        pagesize=A4,
        rightMargin=margin_right,
        leftMargin=margin_left,
        topMargin=margin_top,
        bottomMargin=margin_bottom,
        title="Timetable report",
        author="Timetable generator",
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "TimetableTitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=11,
        leading=12,
        alignment=1,
        textColor=colors.black,
        spaceAfter=2 * mm,
    )

    usable_width = A4[0] - margin_left - margin_right

    light_grey = colors.HexColor("#D0D0D0")
    rule_grey = colors.HexColor("#777777")

    def get_table_data(df):
        headers = [str(col) for col in df.columns]
        display_headers = ["Vuoro" if col == "Block" else col for col in headers]
        data = [display_headers]

        for _, row in df.iterrows():
            formatted_row = []
            for value in row:
                if pd.isna(value):
                    formatted_row.append("")
                else:
                    formatted_row.append(str(value))
            data.append(formatted_row)
        return display_headers, data

    def make_table(df, config, cell_width):
        display_headers, data = get_table_data(df)
        col_count = len(display_headers)
        table = Table(
            data,
            colWidths=[cell_width] * col_count,
            repeatRows=1,
            hAlign="LEFT",
            spaceBefore=0,
            spaceAfter=0,
        )

        shaded_stops = config.get(
            "SHADED_STOPS",
            ["KLA12", "PRA1", "KLA22"],
        )
        shaded_indices = [
            i for i, col in enumerate(display_headers)
            if col in shaded_stops
        ]

        table_style = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.white),
            ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("LEADING", (0, 0), (-1, 0), 11),

            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 8.5),
            ("LEADING", (0, 1), (-1, -1), 10),

            ("LEFTPADDING", (0, 0), (-1, -1), 0.5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0.5),
            ("TOPPADDING", (0, 0), (-1, 0), 1),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
            ("TOPPADDING", (0, 1), (-1, -1), 0.4),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 0.4),

            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),

            ("BOX", (0, 0), (-1, -1), 0.35, rule_grey),
            ("LINEBELOW", (0, 0), (-1, 0), 0.7, colors.black),
            ("LINEBEFORE", (1, 0), (1, -1), 0.45, colors.black),
            ("FONTNAME", (0, 0), (0, -1), "Helvetica"),
            ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ]

        for row_idx in range(3, len(data), 3):
            table_style.append(
                ("LINEBELOW", (0, row_idx), (-1, row_idx), 0.35, colors.black)
            )

        for idx in range(2, col_count):
            table_style.append(
                ("LINEBEFORE", (idx, 0), (idx, -1), 0.15, colors.HexColor("#B0B0B0"))
            )

        for idx in shaded_indices:
            table_style.append(
                ("BACKGROUND", (idx, 0), (idx, -1), light_grey)
            )

        table.setStyle(TableStyle(table_style))
        return table

    def minimum_cell_width(df):
        display_headers, data = get_table_data(df)
        required_widths = []
        for col_idx in range(len(display_headers)):
            text_width = max(
                stringWidth(
                    row[col_idx],
                    "Helvetica",
                    10 if row_idx == 0 else 8.5,
                )
                for row_idx, row in enumerate(data)
            )
            required_widths.append(text_width + 3)
        return max(required_widths)

    def append_stacked_section(elements, route_name, df, config):
        if df.empty:
            print(f"No timetable data for {route_name}; section omitted.")
            return
        cell_width = usable_width / len(df.columns)
        elements.extend([
            Paragraph(route_name, title_style),
            Spacer(1, 1 * mm),
            make_table(df, config, cell_width),
            Spacer(1, 5 * mm),
        ])

    elements = []
    route_index = 0
    while route_index < len(route_timetables):
        route_name, df, config = route_timetables[route_index]
        next_route = (
            route_timetables[route_index + 1]
            if route_index + 1 < len(route_timetables)
            else None
        )

        if (
            route_name == "Hallista linjalle"
            and next_route is not None
            and next_route[0] == "Linjasta halliin"
            and not df.empty
            and not next_route[1].empty
        ):
            next_name, next_df, next_config = next_route
            gap_width = 4 * mm
            total_columns = len(df.columns) + len(next_df.columns)
            cell_width = (usable_width - gap_width) / total_columns
            left_width = len(df.columns) * cell_width
            right_width = len(next_df.columns) * cell_width
            titles_fit = (
                stringWidth(route_name, "Helvetica", 11) <= left_width
                and stringWidth(next_name, "Helvetica", 11) <= right_width
            )

            if (
                cell_width >= max(
                    minimum_cell_width(df),
                    minimum_cell_width(next_df),
                )
                and titles_fit
            ):
                elements.append(Table(
                    [
                        [
                            Paragraph(route_name, title_style),
                            "",
                            Paragraph(next_name, title_style),
                        ],
                        [
                            make_table(df, config, cell_width),
                            "",
                            make_table(next_df, next_config, cell_width),
                        ],
                    ],
                    colWidths=[left_width, gap_width, right_width],
                    style=TableStyle([
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                        ("TOPPADDING", (0, 0), (-1, -1), 0),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ]),
                ))
                elements.append(Spacer(1, 5 * mm))
            else:
                append_stacked_section(elements, route_name, df, config)
                append_stacked_section(elements, next_name, next_df, next_config)
            route_index += 2
            continue

        append_stacked_section(elements, route_name, df, config)
        route_index += 1

    doc.build(elements)
    print(f"PDF successfully generated: {filename}")

# --- EXECUTION ---
raw_blocks = parse_exp_file(f"data-files/{file_name}")
blocks_data = combine_block_trips(raw_blocks)

route_timetables = {}
for route_name, route_config in ROUTES.items():
    print(f"\n================ {route_name} ================")

    timetable_df = generate_timetable(blocks_data, route_config)
    print(timetable_df.to_string(index=False))
    route_timetables[route_name] = timetable_df

pdf_route_order = [
    "Hallista linjalle",
    "Linjasta halliin",
    *[name for name in ROUTES if name not in ("Hallista linjalle", "Linjasta halliin")],
]
export_timetables_to_pdf(
    [
        (route_name, route_timetables[route_name], ROUTES[route_name])
        for route_name in pdf_route_order
    ],
    filename="timetable_11_13.pdf",
)