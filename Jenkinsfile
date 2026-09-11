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
                                    python3 -m venv .venv
                                    . .venv/bin/activate
                                    pip install --no-cache-dir -r requirements-dev.txt
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
            options {
                lock resource: 'erp-vps-heavy'
            }
            steps {
                sh '''
                    cp .env.example .env
                    docker compose -p "$COMPOSE_PROJECT_NAME" -f docker-compose.yml -f docker-compose.test.yml up -d --build postgres
                    docker compose -p "$COMPOSE_PROJECT_NAME" -f docker-compose.yml -f docker-compose.test.yml exec -T postgres \
                        sh -c 'until pg_isready -U "$POSTGRES_USER"; do sleep 1; done'

                    python3 -m venv .venv-integration
                    . .venv-integration/bin/activate
                    pip install --no-cache-dir -r tests/integration/requirements.txt
                    pytest tests/integration/test_db_isolation.py --junitxml=reports/db-isolation-junit.xml
                '''
            }
            post {
                always {
                    sh '''
                        docker compose -p "$COMPOSE_PROJECT_NAME" -f docker-compose.yml -f docker-compose.test.yml down -v --remove-orphans || true
                    '''
                    junit allowEmptyResults: true, testResults: 'reports/db-isolation-junit.xml'
                }
            }
        }
    }

    post {
        always {
            archiveArtifacts allowEmptyArchive: true, artifacts: 'reports/**'
        }
    }
}
