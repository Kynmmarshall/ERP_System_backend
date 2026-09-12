// Backend-owned PRODUCTION PROMOTION pipeline. Promotes an explicit,
// already-built frontend/backend image pair - identified by an exact,
// immutable IMAGE_TAG that the root Jenkinsfile CI job already tested and
// pushed - to the VPS. This file is never triggered automatically by CI
// (no `triggers` block, no upstream job wiring): production promotion is
// always an explicit, manually-started build with a restricted manual
// approval gate before anything on the VPS is mutated.
//
// NOT validated against a live Jenkins controller in this session (no
// credentials/network access to the real instance from this sandbox -
// see docs/security.md and /memories/session/plan.md). Reviewed by hand
// against https://www.jenkins.io/doc/book/pipeline/syntax/ conventions;
// run the Jenkins declarative pipeline linter against the real
// controller before the first real use.
//
// Prerequisites on the Jenkins agent (documented, not provisioned by this
// file): Docker CLI + Compose v2 plugin, jq, curl, this repo checked out
// at a commit whose registry images were already pushed under IMAGE_TAG,
// and the following already configured on the Jenkins controller:
//   - Credential 'erp-registry-credentials' (username/password): registry
//     login for pulling images.
//   - Credential 'erp-smoke-test-account' (username/password): a
//     dedicated, non-production-data smoke-test account's email/password
//     (see ops/deploy/smoke.sh header comment).
//   - DEPLOY_PATH on the agent (default /opt/erp) already holds the
//     production .env, JWT key files and any other secret files
//     referenced by docker-compose.prod.yml - this pipeline never writes
//     or generates real secrets.
//   - An approved list of users/groups allowed to approve the "Approve
//     production promotion" input step (configure via Jenkins folder-level
//     or global authorization, not in this file).
pipeline {
    agent any

    options {
        timeout(time: 45, unit: 'MINUTES')
        disableConcurrentBuilds()
        timestamps()
    }

    parameters {
        string(
            name: 'IMAGE_TAG',
            defaultValue: '',
            description: 'Exact immutable image tag/digest to promote (must already be pushed to the registry by the CI job). Never "latest".'
        )
        string(
            name: 'GIT_COMMIT_SHA',
            defaultValue: '',
            description: 'Backend git commit SHA this IMAGE_TAG was built from (recorded in the release manifest for traceability).'
        )
        string(
            name: 'FRONTEND_GIT_REF',
            defaultValue: '',
            description: 'Frontend git ref (tag/commit) paired with this backend IMAGE_TAG, used only for the candidate E2E validation stage.'
        )
        string(
            name: 'FRONTEND_REPO_URL',
            defaultValue: '',
            description: 'Frontend repository URL (source-control provider not yet decided - see plan.md), used only for the candidate E2E validation stage.'
        )
        string(
            name: 'REGISTRY_HOST',
            defaultValue: '',
            description: 'Container registry host, e.g. registry.example.com (undecided as of plan.md - must be supplied explicitly, never assumed).'
        )
        string(
            name: 'REGISTRY_NAMESPACE',
            defaultValue: '',
            description: 'Registry namespace/org that erp-* images are pushed under.'
        )
        string(
            name: 'ERP_DOMAIN',
            defaultValue: '',
            description: 'Public HTTPS domain this deployment serves (used for the preflight TLS check and smoke tests).'
        )
    }

    environment {
        DEPLOY_PATH = '/opt/erp'
        BACKUP_DIR = "${DEPLOY_PATH}/backups/base"
        WAL_ARCHIVE_DIR = "${DEPLOY_PATH}/backups/wal-archive"
        REGISTRY_CREDENTIALS = credentials('erp-registry-credentials')
        SMOKE_TEST_CREDENTIALS = credentials('erp-smoke-test-account')
    }

    stages {
        stage('Validate parameters') {
            steps {
                script {
                    if (!params.IMAGE_TAG?.trim()) {
                        error 'IMAGE_TAG is required - refusing to guess a floating tag.'
                    }
                    if (params.IMAGE_TAG.trim() == 'latest') {
                        error 'IMAGE_TAG must be an immutable tag/digest, never "latest".'
                    }
                    if (!params.REGISTRY_HOST?.trim() || !params.REGISTRY_NAMESPACE?.trim()) {
                        error 'REGISTRY_HOST and REGISTRY_NAMESPACE are required (registry is not hardcoded - see plan.md).'
                    }
                    if (!params.ERP_DOMAIN?.trim()) {
                        error 'ERP_DOMAIN is required.'
                    }
                }
            }
        }

        stage('Preflight') {
            steps {
                // IMAGE_TAG / REGISTRY_HOST / REGISTRY_NAMESPACE / ERP_DOMAIN are
                // already exported into the shell environment by Jenkins
                // (declarative pipeline parameters are auto-bound to same-named
                // env vars); DEPLOY_PATH comes from the environment{} block above.
                sh './ops/deploy/preflight.sh'
            }
        }

        // Brings up the exact pinned candidate images (never rebuilt) in a
        // disposable, isolated compose project - separate ports/volumes,
        // fresh throwaway database/broker, never the real production
        // stack - then runs the combined E2E smoke suite against it before
        // asking a human to approve production promotion. Torn down
        // unconditionally afterward.
        stage('Validate candidate pair (contracts + E2E)') {
            options {
                lock resource: 'erp-vps-heavy'
            }
            environment {
                CANDIDATE_PROJECT = "erp-candidate-${env.BUILD_NUMBER}"
            }
            steps {
                dir('contracts') {
                    sh '''
                        python3 -m venv .venv
                        . .venv/bin/activate
                        pip install --no-cache-dir -r requirements.txt
                        pytest --junitxml=../reports/candidate-contracts-junit.xml
                    '''
                }
                sh '''
                    set -e
                    python3 -m venv .venv-keys
                    . .venv-keys/bin/activate
                    pip install --no-cache-dir cryptography
                    python scripts/generate_dev_jwt_keys.py

                    # IMAGE_TAG / REGISTRY_HOST / REGISTRY_NAMESPACE are already in
                    # the environment from the pipeline parameters of the same name.
                    export JWT_PRIVATE_KEY_FILE="$WORKSPACE/ops/secrets/dev/jwt_private_key.pem"
                    export JWT_PUBLIC_KEY_FILE="$WORKSPACE/ops/secrets/dev/jwt_public_key.pem"

                    docker login "$REGISTRY_HOST" -u "$REGISTRY_CREDENTIALS_USR" --password-stdin <<< "$REGISTRY_CREDENTIALS_PSW"
                    docker compose -p "$CANDIDATE_PROJECT" -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.test.yml pull
                    docker compose -p "$CANDIDATE_PROJECT" -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.test.yml up -d

                    for service in identity academic finance hr; do
                        docker compose -p "$CANDIDATE_PROJECT" -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.test.yml \
                            run --rm --no-deps "$service" alembic upgrade head
                    done

                    timeout=120
                    deadline=$(( $(date +%s) + timeout ))
                    until curl -fsS -o /dev/null http://127.0.0.1:18081/healthz; do
                        if [ "$(date +%s)" -ge "$deadline" ]; then
                            echo "Candidate stack did not become healthy in time" >&2
                            docker compose -p "$CANDIDATE_PROJECT" -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.test.yml ps >&2
                            exit 1
                        fi
                        sleep 2
                    done
                '''
                dir('frontend-candidate') {
                    checkout([$class: 'GitSCM',
                        branches: [[name: params.FRONTEND_GIT_REF ?: '*/main']],
                        userRemoteConfigs: [[url: params.FRONTEND_REPO_URL ?: '']]
                    ])
                    sh '''
                        npm ci
                        npx playwright install --with-deps chromium
                        E2E_BASE_URL="http://127.0.0.1:18081" npm run test:e2e
                    '''
                }
            }
            post {
                always {
                    sh '''
                        docker compose -p "$CANDIDATE_PROJECT" -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.test.yml \
                            down -v --remove-orphans || true
                    '''
                    junit allowEmptyResults: true, testResults: 'reports/candidate-contracts-junit.xml'
                }
            }
        }

        stage('Approve production promotion') {
            steps {
                input message: "Promote IMAGE_TAG=${params.IMAGE_TAG} (commit ${params.GIT_COMMIT_SHA}) to production at ${params.ERP_DOMAIN}?",
                      ok: 'Promote'
            }
        }

        stage('Pull production images') {
            options {
                lock resource: 'erp-production'
            }
            steps {
                sh '''
                    docker login "$REGISTRY_HOST" -u "$REGISTRY_CREDENTIALS_USR" --password-stdin <<< "$REGISTRY_CREDENTIALS_PSW"
                    cd "$DEPLOY_PATH"
                    docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
                '''
            }
        }

        stage('Capture previous release manifest') {
            options {
                lock resource: 'erp-production'
            }
            steps {
                sh '''
                    if [ -f "$DEPLOY_PATH/releases.log" ]; then
                        echo "Previous release (for rollback reference if this promotion fails):"
                        tail -n 1 "$DEPLOY_PATH/releases.log"
                    else
                        echo "No previous release recorded - this is the first tracked promotion."
                    fi
                '''
            }
        }

        stage('Confirm backup and WAL archive') {
            options {
                lock resource: 'erp-production'
            }
            steps {
                sh './ops/deploy/backup_check.sh'
            }
        }

        stage('Run migrations') {
            options {
                lock resource: 'erp-production'
            }
            steps {
                sh './ops/deploy/migrate.sh'
            }
        }

        stage('Deploy') {
            options {
                lock resource: 'erp-production'
            }
            steps {
                sh './ops/deploy/deploy.sh'
            }
        }

        stage('Smoke test') {
            options {
                lock resource: 'erp-production'
            }
            steps {
                sh '''
                    SMOKE_TEST_EMAIL="$SMOKE_TEST_CREDENTIALS_USR" SMOKE_TEST_PASSWORD="$SMOKE_TEST_CREDENTIALS_PSW" \
                        ./ops/deploy/smoke.sh
                '''
            }
        }

        stage('Record release') {
            options {
                lock resource: 'erp-production'
            }
            steps {
                sh '''
                    GIT_COMMIT="$GIT_COMMIT_SHA" ./ops/deploy/record_release.sh
                '''
            }
        }
    }

    post {
        failure {
            echo '''
Deployment did NOT complete successfully.
Do not assume it is safe to retry blindly - inspect the failed stage's
output first (a failure during "Pull migrations"/"Deploy"/"Smoke test"
may have left the cluster mid-migration or mid-rollout).
If a human operator confirms the previous release's schema is still
compatible with the CURRENT database state, roll back manually by running
(on the VPS, interactively, NOT from this automated pipeline):
    cd /opt/erp && ./ops/deploy/rollback.sh
This is deliberately not automatic: see plan.md - "Database restoration is
a separate explicit recovery procedure, never an automatic destructive
down-migration."
'''
        }
    }
}
