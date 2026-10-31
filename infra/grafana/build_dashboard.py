"""Generates dashboards/operations.json (Grafana prototype, D22). Run: python infra/grafana/build_dashboard.py"""

import json
from pathlib import Path

DS = {"type": "grafana-postgresql-datasource", "uid": "cochleahub-pg"}
LATEST = ("(SELECT id FROM pipeline_runs WHERE status = 'completed' "
          "ORDER BY started_at DESC LIMIT 1)")


def target(sql, fmt="table"):
    return [{"datasource": DS, "refId": "A", "format": fmt, "rawQuery": True,
             "editorMode": "code", "rawSql": sql}]


panels = []


def add(kind, title, sql, x, y, w, h, fmt="table", options=None, field=None, desc=None):
    # one neutral hue: Grafana's default threshold colours (green/red) would read as good/bad
    field = {"color": {"mode": "fixed", "fixedColor": "#2a78d6"}, **(field or {})}
    p = {"id": len(panels) + 1, "type": kind, "title": title, "datasource": DS,
         "gridPos": {"x": x, "y": y, "w": w, "h": h}, "targets": target(sql, fmt),
         "options": options or {}, "fieldConfig": {"defaults": field, "overrides": []}}
    if desc:
        p["description"] = desc
    panels.append(p)


add("stat", "Latest run QC", f"SELECT qc_status FROM pipeline_runs WHERE id = {LATEST}",
    0, 0, 6, 4, options={"reduceOptions": {"calcs": ["lastNotNull"], "fields": "/.*/"},
                         "colorMode": "none", "textMode": "value"})
add("stat", "QC errors", f"SELECT qc_errors FROM pipeline_runs WHERE id = {LATEST}",
    6, 0, 4, 4, options={"colorMode": "none"})
add("stat", "QC warnings", f"SELECT qc_warnings FROM pipeline_runs WHERE id = {LATEST}",
    10, 0, 4, 4, options={"colorMode": "none"})
add("stat", "Assistant turns (7 days)",
    "SELECT count(*) FROM assistant_turns WHERE created_at > now() - interval '7 days'",
    14, 0, 5, 4, options={"colorMode": "none"})
add("stat", "Assistant median latency (s)",
    "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_s) FROM assistant_turns "
    "WHERE created_at > now() - interval '7 days' AND model LIKE 'claude%'",
    19, 0, 5, 4, options={"colorMode": "none"}, field={"decimals": 1, "unit": "s"},
    desc="Claude backend only")
add("table", "Pipeline runs",
    "SELECT left(id::text, 8) AS run, specimen_id AS specimen, started_at, status, "
    "pipeline_version AS version, round(duration_s::numeric, 1) AS duration_s, qc_status, "
    "qc_errors AS errors, qc_warnings AS warnings, qc_info AS info "
    "FROM pipeline_runs ORDER BY started_at DESC", 0, 4, 24, 5)
add("barchart", "QC flags of the latest run",
    f"SELECT code || ' (' || severity || ')' AS flag, count(*) AS n FROM qc_flags "
    f"WHERE run_id = {LATEST} GROUP BY 1 ORDER BY 2 DESC",
    0, 9, 12, 8, options={"orientation": "horizontal", "xField": "flag",
                          "showValue": "auto", "legend": {"showLegend": False}})
add("bargauge", "Structure volume, latest run (mm³)",
    f"SELECT name, volume_mm3 FROM structure_measurements WHERE run_id = {LATEST} "
    "ORDER BY volume_mm3 DESC",
    12, 9, 12, 8, options={"orientation": "horizontal", "displayMode": "basic",
                           "reduceOptions": {"calcs": ["lastNotNull"], "values": True}},
    field={"unit": "none", "decimals": 1},
    desc="Linear scale only: bone and sinus dura dwarf the inner-ear structures")
add("timeseries", "Assistant latency per turn",
    "SELECT created_at AS time, latency_s, model AS metric FROM assistant_turns "
    "WHERE $__timeFilter(created_at) ORDER BY 1", 0, 17, 12, 8, fmt="time_series",
    field={"unit": "s", "custom": {"drawStyle": "points", "pointSize": 6},
           "color": {"mode": "palette-classic"}})  # one colour per model
add("table", "Assistant turns",
    "SELECT created_at, model, stop_reason, round(latency_s::numeric, 1) AS latency_s, "
    "json_array_length(tool_calls::json) AS tools, json_array_length(sources::json) AS cited, "
    "(usage::json ->> 'output_tokens')::int AS output_tokens, error IS NOT NULL AS failed "
    "FROM assistant_turns WHERE $__timeFilter(created_at) ORDER BY created_at DESC LIMIT 200",
    12, 17, 12, 8)

dashboard = {
    "uid": "cochleahub-ops",
    "title": "CochleaHub operations (Grafana prototype)",
    "description": "Stage 8 comparison prototype (D22): the Operations view rebuilt in Grafana "
                   "on the same PostgreSQL, read-only.",
    "tags": ["cochleahub"],
    "timezone": "browser",
    "schemaVersion": 39,
    "time": {"from": "now-7d", "to": "now"},
    "refresh": "1m",
    "panels": panels,
}
out = Path(__file__).parent / "dashboards" / "operations.json"
out.write_text(json.dumps(dashboard, indent=2) + "\n", encoding="utf-8")
print(f"{len(panels)} panels -> {out}")
