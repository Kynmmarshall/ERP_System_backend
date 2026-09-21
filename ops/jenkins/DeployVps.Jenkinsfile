// Single-VPS deployment pipeline. Jenkins runs natively ON the VPS, so every
// step is a local shell command - no SSH, no registry, no image promotion.
// Images are built on the box from the two checked-out repos.
//
// This is the simpler sibling of Deploy.Jenkinsfile. That one promotes an
// exact, already-tested image tag pulled from a registry, which is the
// stronger guarantee ("ship the bytes you tested"). Use this one only while
// there is no registry; the trade-off is that the images deployed here were
// built at deploy time and are therefore not bit-identical to whatever CI
// tested.
//
// Prerequisites on the VPS (documented, NOT provisioned by this file):
//   - Docker Engine + Compose v2 plugin, and the jenkins user in the docker
//     group (or this job running as root).
//   - DEPLOY_PATH holds the real .env and JWT keypair. This pipeline never
//     writes secrets.
//   - The frontend repo checked out as a SIBLING of the backend, because
//     docker-compose.yml builds it from `context: ../ERP_System`.
//   - Credential 'erp-smoke-test-account' (username/password): a dedicated
//     low-privilege account used only by ops/deploy/smoke.sh.
pipeline {
    agent any

    options {
        timeout(time: 30, unit: 'MINUTES')
        disableConcurrentBuilds()
        timestamps()
    }

    parameters {
        string(
            name: 'BACKEND_BRANCH',
            defaultValue: 'main',
            description: 'Backend branch/tag/commit to deploy.'
        )
        string(
            name: 'FRONTEND_BRANCH',
            defaultValue: 'main',
            description: 'Frontend branch/tag/commit to deploy.'
        )
        booleanParam(
            name: 'RUN_MIGRATIONS',
            defaultValue: true,
            description: 'Run alembic upgrade head for all four services before bringing the stack up.'
        )
        string(
            name: 'SMOKE_GATEWAY_URL',
            defaultValue: 'https://ict-erp-system.duckdns.org',
            description: 'Base URL the smoke test hits. The public HTTPS address is the honest default - it exercises host Nginx, TLS and the gateway. Point it at http://127.0.0.1:2022 only to bypass a TLS problem you already know about.'
        )
    }

    environment {
        // Backend lives here; the frontend repo sits next to it as a sibling.
        DEPLOY_PATH = '/root/erp/ERP_System_backend'
        FRONTEND_PATH = '/root/erp/ERP_System'
        COMPOSE_FILES = '-f docker-compose.yml -f docker-compose.vps.yml'
        BUILD_FLAG = '--build'
        ERP_DOMAIN = 'ict-erp-system.duckdns.org'
        SMOKE_TEST_CREDENTIALS = credentials('erp-smoke-test-account')
    }

    stages {
        stage('Update working copies') {
            steps {
                sh '''
                    set -eu
                    git -C "$DEPLOY_PATH" fetch --all --prune
                    git -C "$DEPLOY_PATH" checkout "$BACKEND_BRANCH"
                    git -C "$DEPLOY_PATH" pull --ff-only

                    git -C "$FRONTEND_PATH" fetch --all --prune
                    git -C "$FRONTEND_PATH" checkout "$FRONTEND_BRANCH"
                    git -C "$FRONTEND_PATH" pull --ff-only

                    echo "backend  $(git -C "$DEPLOY_PATH" rev-parse --short HEAD)"
                    echo "frontend $(git -C "$FRONTEND_PATH" rev-parse --short HEAD)"
                '''
            }
        }

        stage('Refuse to deploy without secrets') {
            steps {
                sh '''
                    set -eu
                    cd "$DEPLOY_PATH"
                    test -f .env || { echo "FAIL: $DEPLOY_PATH/.env is missing." >&2; exit 1; }

                    # Deploying with the console MFA provider would pin every
                    # admin sign-in code to 123456 on a public domain. The
                    # identity service also refuses to boot this way once
                    # ENVIRONMENT=production, so fail here with a clear message
                    # rather than on an opaque container crash.
                    if grep -qE '^MFA_EMAIL_PROVIDER=console' .env; then
                        echo "FAIL: .env still selects the console MFA provider." >&2
                        echo "Set MFA_EMAIL_PROVIDER=brevo with a real BREVO_API_KEY before deploying." >&2
                        exit 1
                    fi

                    for var in JWT_PRIVATE_KEY_FILE JWT_PUBLIC_KEY_FILE; do
                        path=$(grep -E "^${var}=" .env | cut -d= -f2-)
                        test -n "$path" || { echo "FAIL: $var is unset in .env" >&2; exit 1; }
                        test -f "$path" || { echo "FAIL: $var points at missing file $path" >&2; exit 1; }
                    done
                '''
            }
        }

        stage('Build images') {
            steps {
                sh '''
                    set -eu
                    cd "$DEPLOY_PATH"
                    docker compose $COMPOSE_FILES build
                '''
            }
        }

        stage('Migrate') {
            when { expression { params.RUN_MIGRATIONS } }
            steps {
                // Strictly before the new code comes up, so N-1 code never
                // meets an N schema mid-rollout.
                sh './ops/deploy/migrate.sh'
            }
        }

        stage('Deploy') {
            steps {
                sh './ops/deploy/deploy.sh'
            }
        }

        stage('Smoke test') {
            steps {
                sh '''
                    set -eu
                    cd "$DEPLOY_PATH"
                    GATEWAY_URL="$SMOKE_GATEWAY_URL" \
                    SMOKE_TEST_EMAIL="$SMOKE_TEST_CREDENTIALS_USR" \
                    SMOKE_TEST_PASSWORD="$SMOKE_TEST_CREDENTIALS_PSW" \
                    ./ops/deploy/smoke.sh
                '''
            }
        }
    }

    post {
        success {
            sh '''
                set -eu
                cd "$DEPLOY_PATH"
                docker compose $COMPOSE_FILES ps
            '''
        }
        failure {
            echo 'Deployment failed. Do NOT blindly re-run this job.'
            echo 'Check `docker compose logs` on the VPS first: a failed migration'
            echo 'may have left the database partially upgraded, in which case'
            echo 'rolling the code back without reviewing the schema will make it worse.'
        }
    }
}
