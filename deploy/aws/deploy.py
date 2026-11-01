"""Deploy CochleaHub to AWS, cost-saving variant (D23). Run from the repo root with the backend
venv: backend/.venv/Scripts/python deploy/aws/deploy.py <step>

Steps, in order (or `all`):
  secrets     create deploy/aws/terraform/secrets.auto.tfvars (random passwords; git-ignored).
              `secrets <email>` adds a budget alert; without an email (AWS free plan, which
              never charges) no budget is created.
  infra       terraform init + apply
  key         store ANTHROPIC_API_KEY from .env in SSM Parameter Store (not in Terraform state)
  image       build the API image and push it to ECR
  frontend    build the dashboard and upload it to the frontend bucket; invalidate CloudFront
  bundle      upload server config + pipeline outputs, meshes and the axial CBCT to S3
  bootstrap   run deploy/aws/server/bootstrap.sh on the instance through SSM
  smoke       check the public URL end to end
  stop        stop the instance between demos (no instance-hour charges; disk still billed)
  start       start it again and point CloudFront at its new address
  destroy     terraform destroy (removes everything, including the data)

AWS credentials come from the standard chain (AWS_PROFILE / ~/.aws/credentials); this script
never reads or prints them.
"""

import base64
import json
import mimetypes
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

import boto3
import httpx

ROOT = Path(__file__).resolve().parents[2]
TF = ROOT / "deploy" / "aws" / "terraform"
SERVER = ROOT / "deploy" / "aws" / "server"
TERRAFORM = shutil.which("terraform") or str(ROOT / ".tools" / "terraform.exe")
SPECIMEN = "zeta"
CBCT_AXIAL = ["01_CBCT_Unembedded/DICOM_rechts_20150826_Z", "02_CBCT_Embedded/DICOM_zeta_20150917_Z"]


def sh(*cmd, cwd=None, capture=False):
    print("$", " ".join(str(c) for c in cmd), flush=True)
    r = subprocess.run([str(c) for c in cmd], cwd=cwd, check=True, text=True,
                       capture_output=capture)
    return r.stdout if capture else None


def outputs() -> dict:
    raw = json.loads(sh(TERRAFORM, "output", "-json", cwd=TF, capture=True))
    return {k: v["value"] for k, v in raw.items()}


def tfvars() -> dict:
    out = {}
    for line in (TF / "secrets.auto.tfvars").read_text().splitlines():
        k, v = line.split("=", 1)
        out[k.strip()] = json.loads(v.strip())
    return out


# --- steps -----------------------------------------------------------------------------------


def step_secrets(email: str | None = None):
    path = TF / "secrets.auto.tfvars"
    if path.exists():
        print(f"{path.name} exists; keeping it")
        return
    values = {
        "basic_auth_password": secrets.token_urlsafe(12),
        "origin_secret": secrets.token_hex(24),
        "postgres_password": secrets.token_urlsafe(24),
        "create_budget": bool(email),
        "alert_email": email or "",
    }
    path.write_text("".join(f"{k} = {json.dumps(v)}\n" for k, v in values.items()))
    print(f"wrote {path.relative_to(ROOT)} (git-ignored)")


def step_infra():
    sh(TERRAFORM, "init", "-input=false", cwd=TF)
    sh(TERRAFORM, "apply", "-input=false", "-auto-approve", cwd=TF)


def step_key():
    env = dict(
        line.split("=", 1) for line in (ROOT / ".env").read_text().splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    )
    key = env.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        sys.exit("ANTHROPIC_API_KEY is empty in .env")
    o = outputs()
    boto3.client("ssm", region_name=o["region"]).put_parameter(
        Name="/cochleahub/anthropic_api_key", Value=key, Type="SecureString", Overwrite=True
    )
    print("stored /cochleahub/anthropic_api_key (SecureString)")


def step_image():
    o = outputs()
    repo = o["ecr_repository_url"]
    token = boto3.client("ecr", region_name=o["region"]).get_authorization_token()
    data = token["authorizationData"][0]
    user, password = base64.b64decode(data["authorizationToken"]).decode().split(":", 1)
    registry = repo.split("/")[0]
    subprocess.run(["docker", "login", "--username", user, "--password-stdin", registry],
                   input=password, text=True, check=True)
    tag = sh("git", "rev-parse", "--short", "HEAD", cwd=ROOT, capture=True).strip()
    sh("docker", "build", "-f", "backend/Dockerfile", "-t", f"{repo}:{tag}", "-t",
       f"{repo}:latest", ".", cwd=ROOT)
    sh("docker", "push", f"{repo}:{tag}")
    sh("docker", "push", f"{repo}:latest")


def step_frontend():
    o = outputs()
    npm = shutil.which("npm") or "npm"
    sh(npm, "run", "build", cwd=ROOT / "frontend")
    dist = ROOT / "frontend" / "dist"
    s3 = boto3.client("s3", region_name=o["region"])
    for f in sorted(dist.rglob("*")):
        if f.is_dir():
            continue
        key = f.relative_to(dist).as_posix()
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        if f.suffix == ".wasm":
            ctype = "application/wasm"
        # hashed assets never change; index.html must always be revalidated
        cache = "no-cache" if key == "index.html" else "public, max-age=31536000, immutable"
        s3.upload_file(str(f), o["frontend_bucket"], key,
                       ExtraArgs={"ContentType": ctype, "CacheControl": cache})
    boto3.client("cloudfront").create_invalidation(
        DistributionId=o["distribution_id"],
        InvalidationBatch={"Paths": {"Quantity": 1, "Items": ["/index.html"]},
                           "CallerReference": str(time.time())},
    )
    print(f"uploaded {sum(1 for f in dist.rglob('*') if f.is_file())} files")


def step_bundle():
    o = outputs()
    s3 = boto3.client("s3", region_name=o["region"])
    files: list[tuple[Path, str]] = [(p, p.name) for p in SERVER.iterdir() if p.is_file()]
    for name in (f"{SPECIMEN}_measurements.json", f"{SPECIMEN}_validation.json",
                 f"{SPECIMEN}_manifest.json"):
        files.append((ROOT / "data" / "outputs" / name, f"data/outputs/{name}"))
    files += [(p, f"data/meshes/{SPECIMEN}/{p.name}")
              for p in sorted((ROOT / "data" / "meshes" / SPECIMEN).glob("*.glb"))]
    for rel in CBCT_AXIAL:  # only the axial series are archived (D8)
        files += [(p, f"data/dataset/{rel}/{p.name}")
                  for p in sorted((ROOT / "Dataset" / rel).glob("*.dcm"))]
    for i, (path, key) in enumerate(files, 1):
        s3.upload_file(str(path), o["deploy_bucket"], f"bundle/{key}")
        if i % 200 == 0:
            print(f"  {i}/{len(files)}", flush=True)
    print(f"uploaded {len(files)} files to s3://{o['deploy_bucket']}/bundle/")


def step_bootstrap():
    o = outputs()
    ssm = boto3.client("ssm", region_name=o["region"])
    image = f"{o['ecr_repository_url']}:latest"
    script = (
        f"aws s3 cp s3://{o['deploy_bucket']}/bundle/bootstrap.sh /opt/cochleahub/bootstrap.sh "
        f"--region {o['region']} && bash /opt/cochleahub/bootstrap.sh {o['deploy_bucket']} "
        f"{image} {o['meshes_bucket']} {o['region']} {o['url']}"
    )
    for _ in range(30):  # the SSM agent registers a minute or two after first boot
        info = ssm.describe_instance_information(
            Filters=[{"Key": "InstanceIds", "Values": [o["instance_id"]]}]
        )["InstanceInformationList"]
        if info and info[0]["PingStatus"] == "Online":
            break
        print("waiting for the SSM agent…", flush=True)
        time.sleep(10)
    cmd = ssm.send_command(
        InstanceIds=[o["instance_id"]], DocumentName="AWS-RunShellScript",
        Parameters={"commands": [script], "executionTimeout": ["3600"]},
        TimeoutSeconds=3600,
    )["Command"]["CommandId"]
    while True:
        time.sleep(10)
        try:
            r = ssm.get_command_invocation(CommandId=cmd, InstanceId=o["instance_id"])
        except ssm.exceptions.InvocationDoesNotExist:
            continue
        print(f"  {r['Status']}", flush=True)
        if r["Status"] not in ("Pending", "InProgress", "Delayed"):
            break
    print(r["StandardOutputContent"][-3000:])
    if r["Status"] != "Success":
        print(r["StandardErrorContent"][-3000:])
        sys.exit(1)


def document_round_trip(c) -> bool:
    """Upload a small reference document, wait until it is indexed, then delete it (D25)."""
    body = f"# Smoke test\n\nDeployment check {time.time_ns()}; safe to delete.\n".encode()
    r = c.post("/api/v1/documents", files={"file": ("smoke-test.md", body)},
               data={"no_patient_data": "true", "title": "Smoke test"})
    if r.status_code != 202:
        return False
    doc_id = r.json()["id"]
    status = "queued"
    for _ in range(30):
        status = c.get(f"/api/v1/documents/{doc_id}").json()["status"]
        if status in ("indexed", "failed"):
            break
        time.sleep(2)
    deleted = c.delete(f"/api/v1/documents/{doc_id}").status_code == 204
    return status == "indexed" and deleted


def step_smoke():
    o = outputs()
    auth = ("cochleahub", tfvars()["basic_auth_password"])
    with httpx.Client(base_url=o["url"], auth=auth, timeout=60) as c:
        checks = [
            ("site", c.get("/").status_code == 200),
            ("spa route", c.get("/specimens/zeta").status_code == 200),
            ("no auth -> 401", httpx.get(o["url"] + "/api/v1/health").status_code == 401),
            ("ready", c.get("/api/v1/health/ready").json().get("status") == "ok"),
            ("missing data -> 404", c.get("/api/v1/specimens/nope").status_code == 404),
        ]
        meshes = c.get("/api/v1/specimens/zeta/meshes").json()["meshes"]
        mesh = httpx.get(meshes[0]["url"], headers={"Origin": o["url"]})
        checks.append(("mesh via presigned S3 URL", mesh.status_code == 200
                       and mesh.content[:4] == b"glTF"))
        series = c.get("/api/v1/specimens/zeta/imaging").json()["series"][0]
        qido = c.get(f"/dicom-web/studies/{series['study_instance_uid']}/series",
                     headers={"Accept": "application/dicom+json"})
        checks.append(("DICOMweb QIDO", qido.status_code == 200))
        checks.append(("DICOMweb write blocked",
                       c.post("/dicom-web/studies", content=b"x").status_code in (403, 405)))
        checks.append(("assistant ready",
                       c.get("/api/v1/assistant/status").json()["backends"]["claude"]["available"]))
        checks.append(("document upload -> indexed -> deleted", document_round_trip(c)))
    for name, ok in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    print(f"\n{o['url']}  (user cochleahub, password in deploy/aws/terraform/secrets.auto.tfvars)")
    if not all(ok for _, ok in checks):
        sys.exit(1)


def step_stop():
    o = outputs()
    ec2 = boto3.client("ec2", region_name=o["region"])
    ec2.stop_instances(InstanceIds=[o["instance_id"]])
    ec2.get_waiter("instance_stopped").wait(InstanceIds=[o["instance_id"]])
    print("instance stopped; the site is down until `deploy.py start`")


def step_start():
    o = outputs()
    ec2 = boto3.client("ec2", region_name=o["region"])
    ec2.start_instances(InstanceIds=[o["instance_id"]])
    ec2.get_waiter("instance_running").wait(InstanceIds=[o["instance_id"]])
    # a stopped instance gets a new public DNS name; apply updates the CloudFront origin
    sh(TERRAFORM, "apply", "-input=false", "-auto-approve", cwd=TF)
    print(f"started; containers restart by themselves. {o['url']} (CloudFront needs a few "
          "minutes to pick up the new origin)")


def step_destroy():
    sh(TERRAFORM, "destroy", "-input=false", "-auto-approve", cwd=TF)


STEPS = {"secrets": step_secrets, "infra": step_infra, "key": step_key, "image": step_image,
         "frontend": step_frontend, "bundle": step_bundle, "bootstrap": step_bootstrap,
         "smoke": step_smoke, "stop": step_stop, "start": step_start,
         "destroy": step_destroy}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in [*STEPS, "all"]:
        sys.exit(__doc__)
    if sys.argv[1] == "all":
        for name in ("infra", "key", "image", "frontend", "bundle", "bootstrap", "smoke"):
            STEPS[name]()
    elif sys.argv[1] == "secrets":
        step_secrets(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        STEPS[sys.argv[1]]()
