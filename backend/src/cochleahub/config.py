from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    dataset_root: Path = REPO_ROOT / "Dataset"
    specimen_id: str = "zeta"
    output_dir: Path = REPO_ROOT / "data"
    # Optional: 3D Slicer executable for reference Segment Statistics (stage 3)
    slicer_exe: Path | None = None

    database_url: str = "postgresql+psycopg://cochleahub:cochleahub@localhost:5432/cochleahub"
    orthanc_url: str = "http://localhost:8042"
    dicomweb_root: str = "http://localhost:8042/dicom-web"
    # DICOMweb base as the browser sees it: same-origin path, proxied to Orthanc by the Vite
    # dev server locally and by the edge in production, so Orthanc is never exposed (D8)
    dicomweb_public_root: str = "/dicom-web"
    cors_origins: list[str] = ["http://localhost:5173"]

    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-5-5"

    aws_region: str = "eu-west-3"
    # Empty endpoint = Amazon S3; set it for a local S3-compatible store (infra/)
    s3_endpoint_url: str | None = None
    s3_mesh_bucket: str = "cochleahub-meshes"
    # None = default AWS credential chain (env, profile, IAM role)
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None

    def resolve(self, p: Path) -> Path:
        return p if p.is_absolute() else (REPO_ROOT / p).resolve()

    @property
    def dataset_path(self) -> Path:
        return self.resolve(self.dataset_root)

    @property
    def output_path(self) -> Path:
        return self.resolve(self.output_dir)


settings = Settings()
