# Build with an immutable base digest and an exact Gigahorse commit:
# docker build --build-arg BASE_IMAGE=<image@sha256:digest> \
#   --build-arg GIGAHORSE_COMMIT=<full-commit-sha> -f docker/gigahorse.Dockerfile .
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

ARG BASE_IMAGE
ARG GIGAHORSE_REPOSITORY=https://github.com/eth-sri/gigahorse-toolchain.git
ARG GIGAHORSE_COMMIT

RUN case "$BASE_IMAGE" in *@sha256:*) ;; *) echo "BASE_IMAGE must use a digest" >&2; exit 1 ;; esac
RUN test -n "$GIGAHORSE_COMMIT"
RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates git \
    && rm -rf /var/lib/apt/lists/*
RUN git clone "$GIGAHORSE_REPOSITORY" /opt/gigahorse \
    && git -C /opt/gigahorse checkout --detach "$GIGAHORSE_COMMIT"

WORKDIR /opt/gigahorse
ENTRYPOINT ["/opt/gigahorse/gigahorse"]
