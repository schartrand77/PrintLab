FROM ghcr.io/home-assistant/home-assistant:stable

USER root

RUN apk add --no-cache git

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY docker/install-ha-bambulab.sh /usr/local/bin/install-ha-bambulab.sh
RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/install-ha-bambulab.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD []
