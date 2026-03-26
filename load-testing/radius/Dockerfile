FROM python:3.11-slim

WORKDIR /app

# Only stdlib + requests needed
RUN pip install --no-cache-dir requests==2.32.3

COPY radius_client.py radius_load.py ./

# Results volume — mount an emptyDir here in K8s to persist outputs
VOLUME ["/app/results"]

CMD ["python", "radius_load.py"]
