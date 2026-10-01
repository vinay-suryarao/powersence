"""Energy/bill calculation aur monthly PDF report."""
import calendar
import io
from datetime import datetime

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

import config

DEVICES = ("light", "lamp", "fan")


def day_energy(day):
    """Ek din ke record se per-device kWh, total kWh aur bill nikalo."""
    kwh = {d: day.get(f"{d}_on_s", 0) / 3600 * config.DEVICE_WATTS[d] / 1000 for d in DEVICES}
    total = sum(kwh.values())
    return kwh, total, total * config.RATE_PER_KWH


def day_row(day):
    """Ek din ka record -> report/chart ki row (hours, kWh, bill, temperature)."""
    kwh, total, cost = day_energy(day)
    temp_count = day.get("temp_count", 0)
    return {
        "date": day["date"],
        **{f"{d}_h": round(day.get(f"{d}_on_s", 0) / 3600, 2) for d in DEVICES},
        **{f"{d}_kwh": round(kwh[d], 3) for d in DEVICES},
        "occupied_h": round(day.get("occupied_s", 0) / 3600, 2),
        "temp_avg": round(day["temp_sum"] / temp_count, 1) if temp_count else None,
        "temp_max": day.get("temp_max"),
        "kwh": round(total, 3),
        "cost": round(cost, 2),
    }


def summarize_month(year, month, days):
    rows = []
    totals = {"kwh": 0.0, "cost": 0.0, "occupied_h": 0.0, **{f"{d}_h": 0.0 for d in DEVICES},
              **{f"{d}_kwh": 0.0 for d in DEVICES}}
    for day in days:
        _, total, cost = day_energy(day)
        row = day_row(day)
        rows.append(row)
        totals["kwh"] += total
        totals["cost"] += cost
        totals["occupied_h"] += row["occupied_h"]
        for d in DEVICES:
            totals[f"{d}_h"] += row[f"{d}_h"]
            totals[f"{d}_kwh"] += row[f"{d}_kwh"]

    days_in_month = calendar.monthrange(year, month)[1]
    active_days = len(rows) or 1
    avg_daily_cost = totals["cost"] / active_days
    return {
        "month": f"{year:04d}-{month:02d}",
        "days": rows,
        "totals": {k: round(v, 3 if k == "kwh" else 2) for k, v in totals.items()},
        "avg_daily_cost": round(avg_daily_cost, 2),
        "projected_month_cost": round(avg_daily_cost * days_in_month, 2) if rows else 0.0,
        "rate_per_kwh": config.RATE_PER_KWH,
        "device_watts": config.DEVICE_WATTS,
    }


def build_pdf(summary):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm,
                            title=f"PowerSense Report {summary['month']}")
    styles = getSampleStyleSheet()
    month_name = datetime.strptime(summary["month"], "%Y-%m").strftime("%B %Y")
    t = summary["totals"]
    story = [
        Paragraph("PowerSense - Monthly Energy Report", styles["Title"]),
        Paragraph(f"{month_name} &nbsp;|&nbsp; Generated: {datetime.now():%d %b %Y, %I:%M %p}", styles["Normal"]),
        Spacer(1, 8 * mm),
    ]

    summary_table = Table([
        ["Total Energy", f"{t['kwh']:.3f} kWh", "Total Bill", f"Rs. {t['cost']:.2f}"],
        ["Avg Daily Bill", f"Rs. {summary['avg_daily_cost']:.2f}", "Projected Month", f"Rs. {summary['projected_month_cost']:.2f}"],
        ["Light ON", f"{t['light_h']:.2f} h", "Lamp ON", f"{t['lamp_h']:.2f} h"],
        ["Fan ON", f"{t['fan_h']:.2f} h", "Room Occupied", f"{t['occupied_h']:.2f} h"],
    ], colWidths=[40 * mm, 45 * mm, 40 * mm, 45 * mm])
    summary_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f2f6fb")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c9d3df")),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [summary_table, Spacer(1, 6 * mm)]

    days = summary["days"]
    if days:
        story.append(Paragraph("Daily Energy Consumption (kWh)", styles["Heading3"]))
        drawing = Drawing(180 * mm, 65 * mm)
        chart = VerticalBarChart()
        chart.x, chart.y = 12 * mm, 10 * mm
        chart.width, chart.height = 160 * mm, 50 * mm
        chart.data = [[d["kwh"] for d in days]]
        chart.categoryAxis.categoryNames = [d["date"][-2:] for d in days]
        chart.categoryAxis.labels.fontSize = 7
        chart.valueAxis.valueMin = 0
        chart.valueAxis.labels.fontSize = 7
        chart.bars[0].fillColor = colors.HexColor("#2f7de1")
        chart.bars[0].strokeColor = None
        drawing.add(chart)
        drawing.add(String(85 * mm, 2 * mm, "Day of month", fontSize=7))
        story += [drawing, Spacer(1, 4 * mm)]

        story.append(Paragraph("Day-wise Details", styles["Heading3"]))
        data = [["Date", "Light (h)", "Lamp (h)", "Fan (h)", "Occupied (h)", "Avg Temp", "kWh", "Bill (Rs.)"]]
        for d in days:
            data.append([
                d["date"], f"{d['light_h']:.2f}", f"{d['lamp_h']:.2f}", f"{d['fan_h']:.2f}",
                f"{d['occupied_h']:.2f}", f"{d['temp_avg']} C" if d["temp_avg"] is not None else "-",
                f"{d['kwh']:.3f}", f"{d['cost']:.2f}",
            ])
        data.append(["TOTAL", f"{t['light_h']:.2f}", f"{t['lamp_h']:.2f}", f"{t['fan_h']:.2f}",
                     f"{t['occupied_h']:.2f}", "", f"{t['kwh']:.3f}", f"{t['cost']:.2f}"])
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3b5c")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e3ebf5")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f7f9fc")]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d3df")),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ]))
        story.append(table)
    else:
        story.append(Paragraph("Is month ka koi data nahi mila.", styles["Normal"]))

    watts = ", ".join(f"{k.title()} {v}W" for k, v in summary["device_watts"].items())
    story += [Spacer(1, 6 * mm), Paragraph(
        f"Calculation basis: {watts}; Rate Rs. {summary['rate_per_kwh']}/kWh. "
        "Energy = ON time x rated power.", styles["Italic"])]

    doc.build(story)
    return buf.getvalue()
