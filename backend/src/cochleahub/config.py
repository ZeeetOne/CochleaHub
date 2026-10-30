from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    dataset_root: Path = REPO_ROOT / "Dataset"
    specimen_id: str = "zeta"
    output_dir: Path = REPO_ROOT / "data"

    database_url: str = "postgresql+psycopg://cochleahub:cochleahub@localhost:5432/cochleahub"
    orthanc_url: str = "http://localhost:8042"
    dicomweb_root: str = "http://localhost:8042/dicom-web"

    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-5-5"

    aws_region: str = "eu-west-3"
    s3_mesh_bucket: str = ""

    def resolve(self, p: Path) -> Path:
        return p if p.is_absolute() else (REPO_ROOT / p).resolve()

    @property
    def dataset_path(self) -> Path:
        return self.resolve(self.dataset_root)

    @property
    def output_path(self) -> Path:
        return self.resolve(self.output_dir)


settings = Settings()
