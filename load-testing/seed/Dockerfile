FROM postgres:16-alpine

COPY seed_load_test.sql /seed_load_test.sql

# Usage:
#   docker run --rm \
#     -e DATABASE_URL="postgres://aaa_app:devpassword@host.docker.internal:5432/aaa" \
#     aaa/aaa-load-test-seed:dev
CMD ["sh", "-c", "psql \"${DATABASE_URL}\" -f /seed_load_test.sql"]
