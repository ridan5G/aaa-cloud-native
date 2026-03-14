FROM grafana/k6:0.55.0

COPY scripts/ /scripts/

# Default: run the load scenario.
# Override at runtime:
#   docker run ... aaa/aaa-load-tester:dev run /scripts/smoke.js
CMD ["run", "/scripts/load.js"]
