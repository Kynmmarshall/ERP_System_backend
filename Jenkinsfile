// Backend CI: lints, type-checks and tests each FastAPI service independently,
// validates the shared event contracts, builds (but does not push) container
// images, and runs the cross-service database-isolation check.
//
// Deployment/promotion is a separate, explicitly-approved pipeline: see
// ops/jenkins/Deploy.Jenkinsfile. This file only runs on pushes/PRs and must
// never hold production credentials.
//
// Prerequisites on the Jenkins agent: Docker CLI + Compose plugin, Python
// 3.13, and enough free RAM/disk for one Postgres + one service image build
// at a time (see docs/jenkins.md once written).
pipeline {
    agent any

    options {
        timeout(time: 30, unit: 'MINUTES')
        disableConcurrentBuilds()
        timestamps()
    }

    environment {
        COMPOSE_PROJECT_NAME = "erp-ci-${env.BUILD_NUMBER}"
        IMAGE_TAG = "${env.GIT_COMMIT ?: 'dev'}".take(12)
    }

    stages {
        stage('Contract tests') {
            steps {
                dir('contracts') {
                    sh '''
                        python3 -m venv .venv
                        . .venv/bin/activate
                        pip install --no-cache-dir -r requirements.txt
                        pytest --junitxml=../reports/contracts-junit.xml
                    '''
                }
            }
            post {
                always {
                    junit allowEmptyResults: true, testResults: 'reports/contracts-junit.xml'
                }
            }
        }

        // Shared by every stage below: a dev JWT keypair (identity signs,
        // every service verifies) and a real, migrated Postgres. All four
        // schemas are created here - no suite calls create_all, they expect
        // migrations to have run. Torn down once at the very end.
        stage('Provision shared test infrastructure') {
            options {
                lock resource: 'erp-vps-heavy'
            }
            steps {
                sh '''
                    cp .env.example .env

                    python3 -m venv .venv-keys
                    . .venv-keys/bin/activate
                    pip install --no-cache-dir cryptography
                    python scripts/generate_dev_jwt_keys.py

                    docker compose -p "$COMPOSE_PROJECT_NAME" -f docker-compose.yml -f docker-compose.test.yml up -d --build postgres
                    docker compose -p "$COMPOSE_PROJECT_NAME" -f docker-compose.yml -f docker-compose.test.yml exec -T postgres \
                        sh -c 'until pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"; do sleep 1; done'

                    cd services/identity
                    python3 -m venv .venv
                    . .venv/bin/activate
                    pip install --no-cache-dir -r requirements-dev.txt
                    DATABASE_URL="postgresql+asyncpg://identity_app:identity_dev_password@127.0.0.1:55432/identity_db" \
                        python -m alembic upgrade head
                    cd "$WORKSPACE"

                    # The other three suites do not call create_all either, so
                    # their schemas have to exist before the matrix runs.
                    for service in academic finance hr; do
                        echo "=== Migrating $service ==="
                        (
                            cd "services/$service"
                            python3 -m venv .venv
                            . .venv/bin/activate
                            pip install --no-cache-dir -r requirements-dev.txt
                            DATABASE_URL="postgresql+asyncpg://${service}_app:${service}_dev_password@127.0.0.1:55432/${service}_db" \
                                python -m alembic upgrade head
                        )
                    done
                '''
            }
        }

        stage('Service checks') {
            matrix {
                axes {
                    axis {
                        name 'SERVICE'
                        values 'identity', 'academic', 'finance', 'hr'
                    }
                }
                stages {
                    stage('Lint, type-check, test') {
                        steps {
                            dir("services/${SERVICE}") {
                                sh '''
                                    [ -d .venv ] || python3 -m venv .venv
                                    . .venv/bin/activate
                                    pip install --no-cache-dir -r requirements-dev.txt

                                    export JWT_PUBLIC_KEY_PATH="$WORKSPACE/ops/secrets/dev/jwt_public_key.pem"
                                    export JWT_PRIVATE_KEY_PATH_FOR_TESTS="$WORKSPACE/ops/secrets/dev/jwt_private_key.pem"
                                    # Every service needs this: without it they fall back to
                                    # the in-container hostname `postgres`, which fails from
                                    # the Jenkins host with "Name or service not known".
                                    export DATABASE_URL="postgresql+asyncpg://${SERVICE}_app:${SERVICE}_dev_password@127.0.0.1:55432/${SERVICE}_db"
                                    if [ "${SERVICE}" = "identity" ]; then
                                        export JWT_PRIVATE_KEY_PATH="$WORKSPACE/ops/secrets/dev/jwt_private_key.pem"
                                    fi

                                    ruff check .
                                    mypy app
                                    pytest --junitxml=../../reports/${SERVICE}-junit.xml \
                                        --cov=app --cov-report=xml:../../reports/${SERVICE}-coverage.xml \
                                        --cov-fail-under=70
                                '''
                            }
                        }
                        post {
                            always {
                                junit allowEmptyResults: true, testResults: "reports/${SERVICE}-junit.xml"
                            }
                        }
                    }
                    stage('Build image') {
                        steps {
                            // Validates the Dockerfile builds; not pushed here.
                            // Promotion pipeline re-builds from the same commit
                            // and pushes only after this job is green.
                            sh "docker build -t erp-${SERVICE}:${IMAGE_TAG} services/${SERVICE}"
                        }
                    }
                }
            }
        }

        stage('Database isolation check') {
            steps {
                sh '''
                    python3 -m venv .venv-integration
                    . .venv-integration/bin/activate
                    pip install --no-cache-dir -r tests/integration/requirements.txt
                    pytest tests/integration/test_db_isolation.py --junitxml=reports/db-isolation-junit.xml
                '''
            }
            post {
                always {
                    junit allowEmptyResults: true, testResults: 'reports/db-isolation-junit.xml'
                }
            }
        }
    }

    post {
        always {
            sh '''
                docker compose -p "$COMPOSE_PROJECT_NAME" -f docker-compose.yml -f docker-compose.test.yml down -v --remove-orphans || true
            '''
            archiveArtifacts allowEmptyArchive: true, artifacts: 'reports/**'
        }
    }
}
