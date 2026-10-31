#!/bin/sh
# Runs the Django test suite inside the image that was just built, against a
# throw-away MySQL 8.4 container, and leaves JUnit XML and a coverage report in
# reports/. The test database lives in tmpfs: fast, and gone afterwards.
#
#   ci/test.sh civicsense:<tag>
set -eu
IMAGE=$1
ID=$(printf '%s' "${BUILD_TAG:-local-$$}" | tr -c 'a-zA-Z0-9_.-' '-' | tr 'A-Z' 'a-z')
NET="ci-$ID" DB="ci-$ID-db"
mkdir -p reports/junit
rm -f reports/junit/*.xml

cleanup() { docker rm -f "$DB" >/dev/null 2>&1 || true; docker network rm "$NET" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create "$NET" >/dev/null
docker run -d --name "$DB" --network "$NET" --tmpfs /var/lib/mysql \
  -e MYSQL_ROOT_PASSWORD=ci-root -e MYSQL_DATABASE=civicsense mysql:8.4 \
  --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci >/dev/null

# A TCP ping only succeeds once MySQL has finished initialising (the temporary
# server it starts first does not listen on the network).
i=0
until docker exec "$DB" mysqladmin ping -h 127.0.0.1 -uroot -pci-root --silent >/dev/null 2>&1; do
  i=$((i + 1)); [ $i -lt 120 ] || { docker logs "$DB" | tail -20; exit 1; }; sleep 1
done
echo "MySQL 8.4 ready after ${i} s"

docker run --rm --network "$NET" -v "$PWD/reports:/app/reports" \
  -e DB_ENGINE=mysql -e DB_HOST="$DB" -e DB_PORT=3306 -e DB_NAME=civicsense \
  -e DB_USER=root -e DB_PASSWORD=ci-root -e DJANGO_SECRET_KEY=ci \
  -e TEST_OUTPUT_DIR=/app/reports/junit \
  --entrypoint sh "$IMAGE" -c '
    pip install --user --quiet --disable-pip-version-check unittest-xml-reporting coverage &&
    python -m coverage run --source=accounts,complaints,dashboard,nlpengine \
        --omit="*/migrations/*,*/tests.py" manage.py test --noinput \
        --testrunner xmlrunner.extra.djangotestrunner.XMLTestRunner &&
    python -m coverage report > reports/coverage.txt &&
    python -m coverage xml -o reports/coverage.xml &&
    echo "coverage: $(tail -1 reports/coverage.txt)"'
