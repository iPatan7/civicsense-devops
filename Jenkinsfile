// CivicSense delivery pipeline (declarative).
//
// Every branch:  static analysis and the image build run in parallel, then the
//                unit tests on MySQL and a dependency audit in parallel, then a
//                smoke test of the image on its own.
// main only:     blue-green deployment to staging and then to production. If the
//                smoke test fails after the production switch, ci/deploy.sh puts
//                the previous release back by itself.
//
// The stages only call scripts in ci/, so every step can also be run by hand.
pipeline {
    agent any

    options {
        skipDefaultCheckout(true)
        timestamps()
        timeout(time: 30, unit: 'MINUTES')
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '30'))
    }

    stages {
        stage('Checkout') {
            steps {
                script {
                    def scmVars = checkout scm
                    env.GIT_COMMIT = scmVars.GIT_COMMIT
                    env.GIT_SHORT = env.GIT_COMMIT.take(8)
                    env.IMAGE = "civicsense:${env.GIT_SHORT}"
                    currentBuild.displayName = "#${env.BUILD_NUMBER} ${env.GIT_SHORT}"
                    currentBuild.description = sh(script: 'git log -1 --format=%s', returnStdout: true).trim()
                }
                sh 'rm -rf reports && mkdir -p reports'
            }
        }

        stage('Build and analyse') {
            parallel {
                stage('Static analysis') {
                    steps { sh 'ci/lint.sh' }
                }
                stage('Build image') {
                    steps {
                        sh 'docker build -t "$IMAGE" --label "org.opencontainers.image.revision=$GIT_COMMIT" .'
                    }
                }
            }
        }

        stage('Test') {
            parallel {
                stage('Unit tests on MySQL') {
                    steps { sh 'ci/test.sh "$IMAGE"' }
                    post {
                        always { junit allowEmptyResults: true, testResults: 'reports/junit/*.xml' }
                    }
                }
                stage('Dependency audit') {
                    steps {
                        // A known vulnerability marks the stage, but does not stop the release.
                        catchError(buildResult: 'SUCCESS', stageResult: 'UNSTABLE') {
                            sh 'ci/audit.sh "$IMAGE"'
                        }
                    }
                }
            }
        }

        stage('Image smoke test') {
            steps { sh 'ci/smoke-image.sh "$IMAGE"' }
        }

        stage('Deploy to staging') {
            when { branch 'main' }
            steps { sh 'ci/deploy.sh staging "$IMAGE"' }
        }

        stage('Deploy to production') {
            when { branch 'main' }
            steps { sh 'ci/deploy.sh production "$IMAGE"' }
        }
    }

    post {
        always {
            archiveArtifacts artifacts: 'reports/**', allowEmptyArchive: true
            sh 'ci/cleanup.sh'
        }
    }
}
