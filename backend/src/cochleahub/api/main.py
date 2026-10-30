"""Read-only API (stage 5). Starts with the dataset manifest; measurement,
distance, comparison and pipeline-run endpoints are added as the pipeline grows."""

import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from cochleahub import __version__
from cochleahub.config import settings

app = FastAPI(title="CochleaHub API", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "pipeline_version": __version__}


@app.get("/specimens")
def list_specimens() -> list[dict]:
    outputs = settings.output_path / "outputs"
    return [
        {"specimen_id": p.name.removesuffix("_manifest.json")}
        for p in sorted(outputs.glob("*_manifest.json"))
    ]


@app.get("/specimens/{specimen_id}")
def get_specimen(specimen_id: str) -> dict:
    path = settings.output_path / "outputs" / f"{specimen_id}_manifest.json"
    if not path.exists():
        raise HTTPException(404, f"No manifest for '{specimen_id}'. Run `cochleahub inspect`.")
    return json.loads(path.read_text())
