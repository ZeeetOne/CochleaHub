# Deploying CochleaHub by hand in the AWS console

The same architecture as the Terraform in `terraform/` (D23), built click by click. It needs no
access keys: everything happens in the browser, including the shell on the server (Session
Manager). The API image is built on the server, so no image registry (ECR) is needed either.

Use this to learn the AWS building blocks. For anything repeatable, use the Terraform: a manual
setup cannot be reviewed, versioned or rebuilt reliably.

```
Browser ──HTTPS──► CloudFront (basic auth, CloudFront Function)
                     ├── "/"                    → S3 frontend bucket (private, OAC)
                     └── "/api/*", "/dicom-web/*" → EC2 :80 nginx → API / Orthanc
Browser ──presigned URL──► S3 meshes bucket (private)
```

Work in **Europe (Paris) eu-west-3** throughout (region selector, top right). Write every name
and value you create into a scratch file; later steps need them.

| Placeholder | Example |
|---|---|
| `<SUFFIX>` | your initials + 4 digits, e.g. `dk4821` (bucket names are global) |
| `<ACCOUNT_ID>` | 12 digits, from the account menu (top right) |
| `<PASSWORD>` | demo password for the site |
| `<ORIGIN_SECRET>` | long random string, header CloudFront sends to the server |
| `<PG_PASSWORD>` | database password |

Generate the three secrets in PowerShell on your laptop (run three times):

```powershell
-join ((48..57)+(65..90)+(97..122) | Get-Random -Count 32 | ForEach-Object {[char]$_})
```

---

## 1. S3 buckets (S3 → Create bucket)

Create three buckets in eu-west-3, each with **Block all public access** left on:

- `cochleahub-frontend-<SUFFIX>`: the built dashboard
- `cochleahub-meshes-<SUFFIX>`: 3D models, written by the API
- `cochleahub-deploy-<SUFFIX>`: server files, data and source code

## 2. Secrets (Systems Manager → Parameter Store → Create parameter)

Create three parameters, each of type **SecureString** with the default key:

| Name | Value |
|---|---|
| `/cochleahub/anthropic_api_key` | your Claude API key (from `.env`) |
| `/cochleahub/postgres_password` | `<PG_PASSWORD>` |
| `/cochleahub/origin_secret` | `<ORIGIN_SECRET>` |

## 3. Role for the server (IAM → Roles → Create role)

1. Trusted entity: **AWS service → EC2**.
2. Permissions: attach **AmazonSSMManagedInstanceCore** (lets you open a shell without SSH).
3. Name: `cochleahub-app` → **Create role**.
4. Open the role → **Add permissions → Create inline policy → JSON**, paste the policy below,
   replacing the placeholders, then name it `cochleahub-app`. This is least privilege: two
   buckets and the `/cochleahub/*` parameters only.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Sid": "Meshes", "Effect": "Allow",
     "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
     "Resource": ["arn:aws:s3:::cochleahub-meshes-<SUFFIX>", "arn:aws:s3:::cochleahub-meshes-<SUFFIX>/*"]},
    {"Sid": "Bundle", "Effect": "Allow",
     "Action": ["s3:GetObject", "s3:ListBucket"],
     "Resource": ["arn:aws:s3:::cochleahub-deploy-<SUFFIX>", "arn:aws:s3:::cochleahub-deploy-<SUFFIX>/*"]},
    {"Sid": "Secrets", "Effect": "Allow", "Action": ["ssm:GetParameter"],
     "Resource": "arn:aws:ssm:eu-west-3:<ACCOUNT_ID>:parameter/cochleahub/*"}
  ]
}
```

## 4. Firewall (EC2 → Security Groups → Create security group)

- Name `cochleahub-app`, VPC: the default VPC.
- Inbound rule: type **HTTP** (80), source **Prefix list** →
  `com.amazonaws.global.cloudfront.origin-facing`. Only CloudFront can reach the server.
- No SSH rule. Leave outbound as is.

## 5. Server (EC2 → Launch instance)

| Setting | Value |
|---|---|
| Name | `cochleahub-app` |
| AMI | Amazon Linux 2023 (x86_64) |
| Instance type | `m7i-flex.large` (free-tier eligible; else `c7i-flex.large`) |
| Key pair | Proceed without a key pair |
| Network | default VPC, auto-assign public IP **enabled**, security group `cochleahub-app` |
| Storage | 30 GiB gp3, **Encrypted** |
| Advanced → IAM instance profile | `cochleahub-app` |
| Advanced → Metadata version | **V2 only (token required)** |
| Advanced → Metadata response hop limit | **2** (containers need the role) |
| Advanced → User data | paste `deploy/aws/terraform/user_data.sh` (installs Docker, Compose and swap) |

Launch it. Note its **Public IPv4 DNS** (`ec2-…eu-west-3.compute.amazonaws.com`).

## 6. Upload server files, data and source (S3 → `cochleahub-deploy-<SUFFIX>`)

On your laptop, make a source archive of the committed code:

```powershell
cd D:\dev\02_personal_projects\in_progress\CochleaHub
git archive -o cochleahub-src.zip HEAD
```

Upload to the deploy bucket (drag and drop keeps folder structure):

| Upload | To |
|---|---|
| `cochleahub-src.zip` | bucket root |
| `deploy/aws/server/docker-compose.yml`, `nginx.conf`, `bootstrap.sh` | `bundle/` |
| `data/outputs/zeta_measurements.json`, `zeta_validation.json`, `zeta_manifest.json` | `bundle/data/outputs/` |
| the 13 files in `data/meshes/zeta/` | `bundle/data/meshes/zeta/` |
| folder `Dataset/01_CBCT_Unembedded/DICOM_rechts_20150826_Z` | `bundle/data/dataset/01_CBCT_Unembedded/` |
| folder `Dataset/02_CBCT_Embedded/DICOM_zeta_20150917_Z` | `bundle/data/dataset/02_CBCT_Embedded/` |

## 7. Edge (CloudFront)

**7a. Function** (CloudFront → Functions → Create function, name `cochleahub-edge`, runtime
cloudfront-js-2.0). Paste `deploy/aws/terraform/edge.js`, replacing `${basic_auth}` with the
output of:

```powershell
[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("cochleahub:<PASSWORD>"))
```

Save, then **Publish**.

**7b. Distribution** (CloudFront → Create distribution). If the console offers flat-rate pricing
plans, choose pay-as-you-go. Then set:

- **Origin 1**: `cochleahub-frontend-<SUFFIX>` bucket. Origin access: **Origin access control
  settings** → create a new OAC.
- **Default behaviour**:
  - viewer protocol **Redirect HTTP to HTTPS**;
  - cache policy **CachingOptimized**;
  - function association **Viewer request → CloudFront Functions → cochleahub-edge**.
- **Settings**: default root object `index.html`; price class "North America and Europe"; no WAF
  (not needed for the demo).
- **Create.** Then copy the bucket policy CloudFront shows into the frontend bucket
  (S3 → bucket → Permissions → Bucket policy).

**7c. Second origin and behaviours** (open the distribution):

- **Origins → Create origin**:
  - domain: the EC2 Public IPv4 DNS;
  - protocol **HTTP only**, port 80;
  - **Add custom header** `X-Origin-Verify` = `<ORIGIN_SECRET>`.
- **Behaviours → Create behaviour**, twice, for path `/api/*` and for `/dicom-web/*`:
  - origin: the EC2 origin;
  - Redirect HTTP to HTTPS;
  - allowed methods **GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE**;
  - cache policy **CachingDisabled**;
  - origin request policy **AllViewerExceptHostHeader**;
  - viewer request function **cochleahub-edge**.

Note the distribution domain, `https://dxxxxxxxx.cloudfront.net`. Deployment takes a few
minutes.

**7d. CORS on the meshes bucket** (S3 → `cochleahub-meshes-<SUFFIX>` → Permissions → CORS):

```json
[{"AllowedMethods": ["GET", "HEAD"], "AllowedOrigins": ["https://dxxxxxxxx.cloudfront.net"],
  "AllowedHeaders": ["*"], "MaxAgeSeconds": 3600}]
```

## 8. Frontend (laptop, then S3)

```powershell
cd frontend
npm run build
```

Upload the **contents** of `frontend/dist` (not the folder itself) to the root of
`cochleahub-frontend-<SUFFIX>`. Afterwards, open one `.wasm` file under `assets/` → Properties →
Metadata and check that `Content-Type` is `application/wasm`. If it is not, edit it; the CT
viewer's codecs need it.

## 9. Install the application (EC2 → instance → Connect → Session Manager)

The shell opens in the browser. Replace the placeholders and run:

```bash
sudo -i
docker --version && docker compose version     # installed by the user data (wait a minute if not)
mkdir -p /opt/cochleahub-src && cd /opt/cochleahub-src
aws s3 cp s3://cochleahub-deploy-<SUFFIX>/cochleahub-src.zip . --region eu-west-3
dnf install -y unzip && unzip -o -q cochleahub-src.zip
docker build -f backend/Dockerfile -t cochleahub-api:latest .     # 5–10 minutes
aws s3 cp s3://cochleahub-deploy-<SUFFIX>/bundle/bootstrap.sh /opt/cochleahub/ --region eu-west-3
bash /opt/cochleahub/bootstrap.sh cochleahub-deploy-<SUFFIX> cochleahub-api:latest \
  cochleahub-meshes-<SUFFIX> eu-west-3 https://dxxxxxxxx.cloudfront.net
docker ps                                       # postgres, orthanc, api, nginx: all Up
```

The bootstrap does the following:

- downloads the bundle;
- reads the three secrets from Parameter Store;
- starts the containers;
- creates the schema;
- loads the run (meshes go to S3);
- uploads the CT to Orthanc;
- builds the documentation index.

## 10. Check

Open `https://dxxxxxxxx.cloudfront.net` and log in as `cochleahub` / `<PASSWORD>`. Then check:

- **Overview:** services all up.
- **Specimen ZETA:** the 3D anatomy loads (meshes from S3), and **Load CT** shows slices
  (DICOMweb).
- **Assistant:** "How close is the facial nerve to the cochlea?" gets a cited answer.
- **Unauthenticated access:** in a private window, `https://dxxxxxxxx.cloudfront.net/api/v1/health`
  returns 401 without the password.

## 11. Remove everything (in this order)

1. **CloudFront:** Disable the distribution, wait until it is deployed, then Delete it. Delete
   the function and the OAC.
2. **EC2:** Terminate the instance; once it is gone, delete the security group.
3. **S3:** Empty, then Delete, each of the three buckets.
4. **Parameter Store:** delete the three `/cochleahub/*` parameters.
5. **IAM:** delete the role `cochleahub-app`.
6. **Billing:** check that no usage keeps growing.
