"""Assistant tools: the read-only API plus documentation search (D11, D20).

Data tools call the same `/api/v1` routes as the dashboard, in-process through an ASGI
transport, so the assistant sees exactly what a user sees, tagged with run and pipeline version
(D9, D17). Clinical question answering framed as tool calls over structured data follows
[Shi2024]; interleaving reasoning with tool actions follows [Yao2023].

Every successful result is returned as a list of `Source`s: one per citable item (a structure, a
distance, a QC flag, a documentation passage). The Claude backend turns them into
`search_result` blocks so the model cites them natively; the local backend numbers them
[S1], [S2], ... A missing-data 404 comes back as an error carrying the API's message, which is
what lets the model abstain instead of guessing [Lee2022].
"""

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from cochleahub.api import API_PREFIX

# Tool definitions in JSON Schema, shared by both backends.
TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_specimens",
        "description": "List specimens with their latest completed pipeline run and QC status. "
        "Call this first when the user does not name a specimen.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_measurements",
        "description": "Per-structure measurements of a specimen: volume (mm3), surface area "
        "(mm2), oriented-bounding-box length/width/thickness (mm), connected components. "
        "Optionally filter by structure names, e.g. ['Scala Tympani', 'Facial Nerve'].",
        "input_schema": {
            "type": "object",
            "properties": {
                "specimen_id": {"type": "string"},
                "structures": {"type": "array", "items": {"type": "string"}},
                "run_id": {"type": "string", "description": "Optional; default latest run."},
            },
            "required": ["specimen_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_cochlea_dimensions",
        "description": "Cochlear A, B and height (mm) of a specimen, each with the published "
        "reference range, its source and whether the value is inside it.",
        "input_schema": {
            "type": "object",
            "properties": {"specimen_id": {"type": "string"}, "run_id": {"type": "string"}},
            "required": ["specimen_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_distances",
        "description": "Minimum distances (mm) between critical structures of a specimen "
        "(facial nerve, chorda tympani, scala tympani, scala vestibuli) with their meaning.",
        "input_schema": {
            "type": "object",
            "properties": {"specimen_id": {"type": "string"}, "run_id": {"type": "string"}},
            "required": ["specimen_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "compare_metric",
        "description": "One metric across all specimens with the published range if one "
        "exists. Per-structure metrics need `structure`.",
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {
                    "type": "string",
                    "enum": [
                        "volume_mm3", "surface_area_mm2", "length_mm", "width_mm",
                        "thickness_mm", "cochlea_a_mm", "cochlea_b_mm", "cochlea_height_mm",
                    ],
                },
                "structure": {"type": "string"},
            },
            "required": ["metric"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_qc_flags",
        "description": "Automatic quality-control flags of a specimen's latest completed run "
        "(severity, code, structure, message, value, limit, source).",
        "input_schema": {
            "type": "object",
            "properties": {
                "specimen_id": {"type": "string"},
                "severity": {"type": "string", "enum": ["error", "warning", "info"]},
            },
            "required": ["specimen_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_validation",
        "description": "Validation of a specimen's latest run: relative volume/area difference "
        "vs. 3D Slicer, and surface distance (mean/p95/max mm) vs. the dataset's meshes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "specimen_id": {"type": "string"},
                "reference": {"type": "string", "enum": ["slicer", "dataset_mesh"]},
            },
            "required": ["specimen_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_docs",
        "description": "Search CochleaHub documentation and the documents users uploaded to "
        "the library (protocols, guidelines, papers): what each measurement means, the "
        "dataset, QC flag codes, design decisions with their literature basis, validation "
        "results, how to use the dashboard. Use for any 'what/why/how' question.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
]

TOOL_NAMES = {t["name"] for t in TOOLS}


@dataclass
class Source:
    source: str  # stable identifier: API path with run id, or doc path#section
    title: str
    text: str


@dataclass
class ToolOutcome:
    ok: bool
    sources: list[Source] = field(default_factory=list)
    error: str | None = None
    summary: str = ""  # one line for the UI ("Measurements of ZETA, run 19ac527c")


def run_label(p: dict) -> str:
    return f"run {p['run_id'][:8]} · pipeline v{p['pipeline_version']} · QC {p['qc_status']}"


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(", ", ": "))


def validate(name: str, args: Any) -> str | None:
    """Minimal schema check; tool inputs may stream in partially (eager input streaming)."""
    spec = next(t for t in TOOLS if t["name"] == name)["input_schema"]
    if not isinstance(args, dict):
        return "input must be an object"
    for key in spec.get("required", []):
        if not isinstance(args.get(key), str) or not args[key]:
            return f"missing required string '{key}'"
    unknown = set(args) - set(spec.get("properties", {}))
    if unknown:
        return f"unknown fields {sorted(unknown)}"
    for key, prop in spec.get("properties", {}).items():
        if key in args and "enum" in prop and args[key] not in prop["enum"]:
            return f"'{key}' must be one of {prop['enum']}"
    return None


class ToolExecutor:
    def __init__(self, index=None, client: httpx.AsyncClient | None = None):
        self.index = index
        if client is None:
            from cochleahub.api.main import app  # imported late: main imports this module

            client = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://cochleahub"
            )
        self.client = client

    async def get(self, path: str, **params) -> tuple[int, Any]:
        params = {k: v for k, v in params.items() if v is not None}
        r = await self.client.get(f"{API_PREFIX}{path}", params=params)
        body = r.json()
        return r.status_code, body

    async def run(self, name: str, args: dict) -> ToolOutcome:
        if name not in TOOL_NAMES:
            return ToolOutcome(False, error=f"Unknown tool '{name}'.")
        if problem := validate(name, args):
            return ToolOutcome(False, error=f"Invalid input for {name}: {problem}.")
        if isinstance(args.get("specimen_id"), str):
            # users and models write "ZETA"; specimen ids are stored lower-case
            args = {**args, "specimen_id": args["specimen_id"].strip().lower()}
        try:
            return await getattr(self, f"_{name}")(**args)
        except httpx.HTTPError as e:
            return ToolOutcome(False, error=f"API unreachable: {e}")

    def _missing(self, status: int, body: Any) -> ToolOutcome:
        detail = body.get("detail") if isinstance(body, dict) else body
        prefix = "No data" if status == 404 else f"API error {status}"
        return ToolOutcome(False, error=f"{prefix}: {detail}")

    async def _list_specimens(self) -> ToolOutcome:
        status, body = await self.get("/specimens")
        if status != 200:
            return self._missing(status, body)
        sources = [
            Source(
                source=f"api:{API_PREFIX}/specimens/{s['id']}",
                title=f"Specimen {s['id'].upper()}",
                text=dumps(s),
            )
            for s in body
        ]
        return ToolOutcome(True, sources, summary=f"{len(body)} specimen(s)")

    async def _get_measurements(self, specimen_id, structures=None, run_id=None):
        status, body = await self.get(f"/specimens/{specimen_id}/measurements", run_id=run_id)
        if status != 200:
            return self._missing(status, body)
        p = body["provenance"]
        rows = body["structures"]
        if structures:
            wanted = {s.lower() for s in structures}
            unknown = wanted - {r["name"].lower() for r in rows}
            rows = [r for r in rows if r["name"].lower() in wanted]
            if not rows:
                names = ", ".join(r["name"] for r in body["structures"])
                return ToolOutcome(
                    False, error=f"No data: no structure named {sorted(unknown)}. "
                    f"Available: {names}."
                )
        base = f"api:{API_PREFIX}/specimens/{specimen_id}/measurements?run_id={p['run_id']}"
        sources = [
            Source(
                source=f"{base}#{r['name']}",
                title=f"{specimen_id.upper()} · {r['name']} · {run_label(p)}",
                text=dumps({**r, "units": "mm3, mm2, mm"}),
            )
            for r in rows
        ]
        return ToolOutcome(True, sources, summary=f"Measurements of {specimen_id.upper()}, "
                           f"{len(rows)} structure(s), {run_label(p)}")

    async def _get_cochlea_dimensions(self, specimen_id, run_id=None):
        status, body = await self.get(f"/specimens/{specimen_id}/cochlea", run_id=run_id)
        if status != 200:
            return self._missing(status, body)
        p = body["provenance"]
        base = f"api:{API_PREFIX}/specimens/{specimen_id}/cochlea?run_id={p['run_id']}"
        sources = [
            Source(
                source=f"{base}#{key}",
                title=f"{specimen_id.upper()} · cochlea {key} · {run_label(p)}",
                text=dumps({"dimension": key, **body[key], "method": body["method"]}),
            )
            for key in ("a", "b", "height")
        ]
        return ToolOutcome(True, sources, summary=f"Cochlear dimensions of "
                           f"{specimen_id.upper()}, {run_label(p)}")

    async def _get_distances(self, specimen_id, run_id=None):
        status, body = await self.get(f"/specimens/{specimen_id}/distances", run_id=run_id)
        if status != 200:
            return self._missing(status, body)
        p = body["provenance"]
        base = f"api:{API_PREFIX}/specimens/{specimen_id}/distances?run_id={p['run_id']}"
        sources = [
            Source(
                source=f"{base}#{d['from_structure']}-{d['to_structure']}",
                title=f"{specimen_id.upper()} · {d['from_structure']} → {d['to_structure']} · "
                f"{run_label(p)}",
                text=dumps({k: d[k] for k in ("from_structure", "to_structure", "meaning",
                                               "distance_mm")}),
            )
            for d in body["distances"]
        ]
        return ToolOutcome(True, sources, summary=f"Distances of {specimen_id.upper()}, "
                           f"{run_label(p)}")

    async def _compare_metric(self, metric, structure=None):
        status, body = await self.get("/compare", metric=metric, structure=structure)
        if status != 200:
            return self._missing(status, body)
        what = f"{metric}" + (f" of {structure}" if structure else "")
        sources = [
            Source(
                source=f"api:{API_PREFIX}/compare?metric={metric}&structure={structure or ''}"
                f"#{v['specimen_id']}",
                title=f"{v['specimen_id'].upper()} · {what}"
                + (f" · {run_label(v['provenance'])}" if v["provenance"] else ""),
                text=dumps({"specimen_id": v["specimen_id"], "value": v["value"],
                            "unit": body["unit"]}),
            )
            for v in body["values"]
        ]
        if ref := body["reference"]:
            sources.append(Source(
                source=f"api:{API_PREFIX}/reference-ranges#{metric}",
                title=f"Published range for {what} [{ref['source']}]",
                text=dumps(ref),
            ))
        return ToolOutcome(True, sources, summary=f"Comparison of {what}")

    async def _latest_run_id(self, specimen_id) -> tuple[str | None, ToolOutcome | None]:
        status, body = await self.get(f"/specimens/{specimen_id}")
        if status != 200:
            return None, self._missing(status, body)
        if not body["latest_run"]:
            return None, ToolOutcome(
                False, error=f"No data: specimen '{specimen_id}' has no completed pipeline run."
            )
        return body["latest_run"]["id"], None

    async def _get_qc_flags(self, specimen_id, severity=None):
        run_id, failed = await self._latest_run_id(specimen_id)
        if failed:
            return failed
        status, body = await self.get(f"/runs/{run_id}/qc", severity=severity)
        if status != 200:
            return self._missing(status, body)
        p = body["provenance"]
        base = f"api:{API_PREFIX}/runs/{run_id}/qc"
        sources = [Source(
            source=f"{base}#summary",
            title=f"{specimen_id.upper()} · QC summary · {run_label(p)}",
            text=dumps({"status": body["status"], "counts": body["counts"],
                        "tolerances": body["tolerances"]}),
        )] + [
            Source(
                source=f"{base}#{i}-{f['code']}",
                title=f"{specimen_id.upper()} · QC {f['severity']} {f['code']}"
                + (f" · {f['structure']}" if f["structure"] else ""),
                text=dumps(f),
            )
            for i, f in enumerate(body["flags"])
        ]
        return ToolOutcome(True, sources, summary=f"QC of {specimen_id.upper()}: "
                           f"{body['status']}, {len(body['flags'])} flag(s), {run_label(p)}")

    async def _get_validation(self, specimen_id, reference=None):
        run_id, failed = await self._latest_run_id(specimen_id)
        if failed:
            return failed
        status, body = await self.get(f"/runs/{run_id}/validation", reference=reference)
        if status != 200:
            return self._missing(status, body)
        p = body["provenance"]
        sources = [
            Source(
                source=f"api:{API_PREFIX}/runs/{run_id}/validation#{r['reference']}-"
                f"{r['structure']}",
                title=f"{specimen_id.upper()} · {r['structure']} vs {r['reference']} · "
                f"{run_label(p)}",
                text=dumps(r),
            )
            for r in body["results"]
        ]
        if not sources:
            return ToolOutcome(False, error=f"No data: no validation results for run {run_id}.")
        return ToolOutcome(True, sources, summary=f"Validation of {specimen_id.upper()}, "
                           f"{len(sources)} row(s), {run_label(p)}")

    async def _search_docs(self, query):
        if self.index is None:
            return ToolOutcome(False, error="Documentation search is not available.")
        hits = self.index.search(query, k=5)
        if not hits:
            return ToolOutcome(False, error=f"No data: no documentation matches '{query}'.")
        sources = [Source(source=h.chunk.id, title=h.chunk.title, text=h.chunk.text) for h in hits]
        return ToolOutcome(True, sources, summary=f"Documentation: {len(hits)} passage(s) for "
                           f"'{query}'")
