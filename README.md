# CivicSense: build, test and deploy on autopilot

CivicSense is a civic complaint platform built with Django and MySQL. Citizens report problems like potholes, overflowing garbage or broken street lights in plain language; a small NLP engine routes each complaint to the right department, merges repeat reports and ranks everything by priority for the officers.

This repository is about **delivering** that application automatically. A push to a feature branch is linted, built, tested against a real MySQL database and audited. A merge to `main` goes on to a staging environment and then to production, using a blue-green switch so users never see the release happen, and the release is undone by itself if the smoke test fails after the switch.

It is my project for **DevOps Process Automation Lab (25CAP-732)**, MCA Cloud Computing & DevOps, Chandigarh University (class group 25CAP-732:P::GP-A, guided by Mr. Danish Rashid Pala). The project report is in [`report/`](report/). The containerisation of the same application is in [civicsense-docker](https://github.com/iPatan7/civicsense-docker).

## The pipeline

```
 feature branch ──► GitHub Actions (on the pull request)  ─┐
       │                                                   │  both must be green
       └──────────► Jenkins: lint ║ build ─► tests ║ audit ─► image smoke test
                                                           │
 merge to main ─────► Jenkins, same stages, then:          ▼
                      staging  (blue-green + smoke test)
                      production (blue-green + smoke test, automatic rollback)
```

| Path | What it is |
|---|---|
| `Jenkinsfile` | Declarative pipeline. Every branch is built and tested; only `main` is deployed. |
| `jenkins/` | Jenkins configured as code: `plugins.txt`, `casc.yaml` (security, settings and the multibranch job) and `run-jenkins.sh`, which builds the whole controller from these files. |
| `ci/lint.sh` | flake8 and bandit in a pinned tools image (`ci/Dockerfile.tools`). Syntax errors, undefined names and high-severity findings fail the build. |
| `ci/test.sh` | The Django test suite inside the freshly built image, against a throw-away MySQL 8.4 in tmpfs. Writes JUnit XML and a coverage report. |
| `ci/audit.sh` | Lists the exact packages inside the image and checks them with pip-audit. |
| `ci/smoke-image.sh` | Boots the image on its own and checks `/healthz` and that it does not run as root. |
| `ci/deploy.sh` | Blue-green deployment of one environment, plus `rollback` and `status`. |
| `ci/smoke.sh` | Seven checks through the public address, including a real login. |
| `ci/traffic.sh`, `ci/measure.sh` | Send requests during a deployment and count the failures. |
| `deploy/compose.yml` | One environment: MySQL, two web slots (blue and green) and nginx. |
| `deploy/env/*.env` | What differs between staging and production. Secrets are generated on the first deployment and never committed. |
| `.github/workflows/ci.yml` | GitHub Actions: tests on a MySQL service container, then an image build and smoke test. |
| `Dockerfile`, `docker/` | The two-stage production image and its entrypoint. |

## Running it

You need Docker with the Compose plugin and Java 21+ for Jenkins.

```bash
git clone https://github.com/iPatan7/civicsense-devops.git
cd civicsense-devops

# Jenkins, built from jenkins/plugins.txt and jenkins/casc.yaml, on http://localhost:8090
JENKINS_ADMIN_PASSWORD='choose-one' jenkins/run-jenkins.sh
```

The `CivicSense` job scans this repository every minute and builds every branch. You can also run any stage by hand:

```bash
docker build -t civicsense:try .
ci/test.sh civicsense:try                  # 40 tests on MySQL 8.4
ci/deploy.sh staging civicsense:try        # http://localhost:8091
ci/deploy.sh production civicsense:try     # http://localhost:8092
ci/deploy.sh production status             # which slot is live
ci/deploy.sh production rollback           # back to the previous release
```

Demo accounts (loaded on the first deployment of an environment): `admin` / `admin123`, `officer` / `civic123`, `citizen1` / `civic123`. They are throwaway demo credentials.
