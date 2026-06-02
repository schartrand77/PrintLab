FROM python:3.12-slim

ARG HA_BAMBULAB_REPO=https://github.com/greghesp/ha-bambulab.git
ARG HA_BAMBULAB_REF=main
ARG ORCA_LINUXDIR_URL=

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/opt
ENV ADMIN_EMAIL=
ENV PRINTLAB_CONFIG_PATH=/config/config.json

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        ffmpeg \
        git \
        libegl1 \
        libgstreamer-plugins-base1.0-0 \
        libgstreamer1.0-0 \
        libgtk-3-0t64 \
        libopengl0 \
        libwebkit2gtk-4.1-0 \
        libwebpdecoder3 \
        libwebpdemux2 \
    && rm -rf /var/lib/apt/lists/*

RUN if [ -n "${ORCA_LINUXDIR_URL}" ]; then \
        mkdir -p /opt/orca \
        && curl -fsSL "${ORCA_LINUXDIR_URL}" | tar -xz -C /opt/orca \
        && chmod +x /opt/orca/bin/orca-slicer \
        && printf '%s\n' \
            '#!/bin/sh' \
            'export LD_LIBRARY_PATH=/opt/orca/bin${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}' \
            'exec /opt/orca/bin/orca-slicer "$@"' \
            > /usr/local/bin/orca-slicer \
        && chmod +x /usr/local/bin/orca-slicer; \
    fi

RUN git clone --depth 1 --branch "${HA_BAMBULAB_REF}" "${HA_BAMBULAB_REPO}" /tmp/ha-bambulab \
    && cp -a /tmp/ha-bambulab/custom_components/bambu_lab/pybambu /opt/pybambu \
    && rm -rf /tmp/ha-bambulab

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app
COPY public /app/public
COPY docker/start-printlab.sh /usr/local/bin/start-printlab.sh
RUN chmod +x /usr/local/bin/start-printlab.sh \
    && mkdir -p /data /config

VOLUME ["/data", "/config"]

EXPOSE 8080

CMD ["/usr/local/bin/start-printlab.sh"]
