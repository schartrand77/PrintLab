FROM python:3.12-slim

ARG HA_BAMBULAB_REPO=https://github.com/greghesp/ha-bambulab.git
ARG HA_BAMBULAB_REF=main

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/opt

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch "${HA_BAMBULAB_REF}" "${HA_BAMBULAB_REPO}" /tmp/ha-bambulab \
    && cp -a /tmp/ha-bambulab/custom_components/bambu_lab/pybambu /opt/pybambu \
    && rm -rf /tmp/ha-bambulab

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app
COPY docker/start-printlab.sh /usr/local/bin/start-printlab.sh
RUN chmod +x /usr/local/bin/start-printlab.sh

EXPOSE 8080

CMD ["/usr/local/bin/start-printlab.sh"]
