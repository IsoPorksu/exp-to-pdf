from reportlab.lib.pagesizes import A4
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle,
    Paragraph, Spacer, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import mm
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
    "Hallivuorot": {
        "ROUTE_SHAPE": [
            "RSV_PO",
            "RUS2",
            "TTP2",
            "EL2",
            "PRA2",
            "LPA",  # Index 5: First occurrence (arrival / pre-pivot)
            "LPA",  # Index 6: Second occurrence (departure / post-pivot)
            "PRA1",
            "EL1",
            "TTP1",
            "RUS1",
            "RSV_PI",
        ],
        "PIVOT_STOP": "LPA",
        "SORT_INDICES": [3, 8],  # Fallback sort indices for routes without MÄR
        "MATCH_PATTERNS": [["RUS1"], ["RUS2"]],
        "SHADED_STOPS": ["PRA2", "LPA"],
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
  second_pivot = (
      pivot_indices[1] if len(pivot_indices) > 1 else len(route_shape) // 2
  )

  mapping = {}
  last_time_val = -1

  if force_half == "pre":
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
  second_pivot_idx = (
      pivot_indices[1] if len(pivot_indices) > 1 else len(route_shape) // 2
  )

  formatted_trips = []

  for block in blocks:
    block_id = block["block_id"]
    for trip_idx, trip in enumerate(block["trips"]):
      if not trip_matches_patterns(trip, match_patterns):
        continue

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
        mapping, count = map_trip_to_shape(trip, route_shape, pivot_stop)
        if mapping:
          is_post_pivot = any(
              idx >= second_pivot_idx for idx in mapping.keys()
          )

      if count >= 2 and mapping:
        formatted_trips.append({
            "block_id": block_id,
            "trip_obj": trip,
            "trip_idx": trip_idx,
            "mapping": mapping,
            "start_time": trip["start_time"],
            "end_time": trip["end_time"],
            "is_post_pivot": is_post_pivot,
        })

  rows = []
  used_pre_pivot_ft_ids = set()

  MIN_LAYOVER_MINUTES = -15
  MAX_LAYOVER_MINUTES = 180

  for ft in formatted_trips:
    if ft["is_post_pivot"] and ft.get("mapping"):
      row = {"Block": ft["block_id"]}
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
      for idx, t_val in ft["mapping"].items():
        row[idx] = t_val
      rows.append(row)

  if not rows:
    return pd.DataFrame()

  table_data = []
  for r in rows:
    row_dict = {"Block": r.get("Block", "")}
    for i in range(len(route_shape)):
      row_dict[i] = r.get(i, "")
    table_data.append(row_dict)

  df = pd.DataFrame(table_data)

  mar_indices = [
      i for i, stop in enumerate(route_shape) if stop.startswith("MÄR")
  ]
  fallback_indices = config.get("SORT_INDICES", [])

  def get_sort_key(row_series):
    row_dict = row_series.to_dict()
    mar_times = []
    for idx in mar_indices:
      t = time_to_min(row_dict.get(idx, ""))
      if t >= 0:
        mar_times.append(t)

    if mar_times:
      return min(mar_times)

    for idx in fallback_indices:
      t = time_to_min(row_dict.get(idx, ""))
      if t >= 0:
        return t

    valid_times = []
    for k, val in row_dict.items():
      if k != "Block":
        t = time_to_min(val)
        if t >= 0:
          valid_times.append(t)
    return min(valid_times) if valid_times else 99999

  df["_sort_val"] = df.apply(get_sort_key, axis=1)
  df_sorted = (
      df.sort_values(by="_sort_val").drop(columns=["_sort_val"]).reset_index(drop=True)
  )

  df_sorted.columns = ["Block"] + route_shape

  return df_sorted


def export_timetable_to_pdf(
    route_name,
    df,
    filename="timetable_report.pdf",
    config=None,
):
    """Export a compact, portrait A4 timetable resembling the reference."""

    if df.empty:
        print(f"No timetable data for {route_name}; PDF not generated.")
        return

    config = config or {}

    # --- Page setup: portrait A4 ---
    margin_left = 7 * mm
    margin_right = 7 * mm
    margin_top = 9 * mm
    margin_bottom = 8 * mm

    doc = SimpleDocTemplate(
        filename,
        pagesize=A4,
        rightMargin=margin_right,
        leftMargin=margin_left,
        topMargin=margin_top,
        bottomMargin=margin_bottom,
        title=f"Timetable {route_name}",
        author="Timetable generator",
    )

    styles = getSampleStyleSheet()

    # Plain black heading, like a printed timetable rather than a report.
    title_style = ParagraphStyle(
        "TimetableTitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7,
        leading=8,
        alignment=1,
        textColor=colors.black,
        spaceAfter=2 * mm,
    )

    elements = [
        Paragraph(
            f"Timetable — {route_name}",
            title_style,
        ),
        Spacer(1, 1 * mm),
    ]

    # --- Column labels ---
    # Keep the existing DataFrame column names and order.
    headers = [str(col) for col in df.columns]

    data = [headers]

    for _, row in df.iterrows():
        formatted_row = []
        for value in row:
            if pd.isna(value):
                formatted_row.append("")
            else:
                formatted_row.append(str(value))
        data.append(formatted_row)

    # --- Compact column widths ---
    usable_width = A4[0] - margin_left - margin_right
    col_count = len(headers)

    # The first column contains the block/vehicle number.
    block_width = 9 * mm
    remaining_width = usable_width - block_width

    if col_count > 1:
        stop_width = remaining_width / (col_count - 1)
        col_widths = [block_width] + [
            stop_width
        ] * (col_count - 1)
    else:
        col_widths = [usable_width]

    # --- Table construction ---
    table = Table(
        data,
        colWidths=col_widths,
        repeatRows=1,
        hAlign="LEFT",
        spaceBefore=0,
        spaceAfter=0,
    )

    # Selected stop columns to shade. Use the actual DataFrame names.
    # Override this list in ROUTES if you want different highlighting.
    shaded_stops = config.get(
        "SHADED_STOPS",
        ["KLA12", "PRA1", "KLA22"],
    )

    shaded_indices = [
        i for i, col in enumerate(headers)
        if col in shaded_stops
    ]

    # A subtle grey fill similar to the reference timetable.
    light_grey = colors.HexColor("#D0D0D0")
    rule_grey = colors.HexColor("#777777")

    table_style = [
        # Header
        ("BACKGROUND", (0, 0), (-1, 0), colors.white),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, 0), 5.8),
        ("LEADING", (0, 0), (-1, 0), 6.2),

        # Body
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -1), 5.5),
        ("LEADING", (0, 1), (-1, -1), 6.0),

        # Compact padding
        ("LEFTPADDING", (0, 0), (-1, -1), 0.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0.5),
        ("TOPPADDING", (0, 0), (-1, 0), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
        ("TOPPADDING", (0, 1), (-1, -1), 0.3),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 0.3),

        # Align times and stop codes centrally.
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),

        # No heavy box around the table.
        ("LINEBELOW", (0, 0), (-1, 0), 0.7, colors.black),
        ("LINEBELOW", (0, 1), (-1, -1), 0.15, rule_grey),

        # Slightly stronger divider after the block number.
        ("LINEBEFORE", (1, 0), (1, -1), 0.45, colors.black),

        # Keep the first column readable.
        ("FONTNAME", (0, 0), (0, -1), "Helvetica"),

        # White background by default, without alternating row fills.
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
    ]

    # Shade selected stop columns from header through final row.
    for idx in shaded_indices:
        table_style.extend([
            ("BACKGROUND", (idx, 0), (idx, -1), light_grey),
        ])

    table.setStyle(TableStyle(table_style))
    elements.append(table)

    doc.build(elements)
    print(f"PDF successfully generated: {filename}")

# --- EXECUTION ---
raw_blocks = parse_exp_file(f"data-files/{file_name}")
blocks_data = combine_block_trips(raw_blocks)

for route_name, route_config in ROUTES.items():
    print(f"\n================ {route_name} ================")

    timetable_df = generate_timetable(blocks_data, route_config)
    print(timetable_df.to_string(index=False))

    pdf_filename = f"timetable_{route_name.replace('/', '_')}.pdf"

    export_timetable_to_pdf(
        route_name,
        timetable_df,
        filename=pdf_filename,
        config=route_config,
    )