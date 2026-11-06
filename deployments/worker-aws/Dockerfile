# Build the reviewed cloud_runtime image first; supply its immutable local/image digest.
ARG MISSION_CONTROL_BASE_IMAGE
FROM ${MISSION_CONTROL_BASE_IMAGE}
# A separately reviewed public configuration directory, never the repository or .env.
COPY --chown=10001:10001 deployments/worker-aws/config/ /etc/mission-control/
CMD ["python", "-m", "mission_control.bootstrap.worker"]
