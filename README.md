# PrintLab

Unraid-ready Docker app for running **Home Assistant** with the
[`greghesp/ha-bambulab`](https://github.com/greghesp/ha-bambulab) custom integration automatically installed.

## What this image does

- Starts from the official Home Assistant container image.
- On container startup, clones `ha-bambulab` and copies
  `custom_components/bambu_lab` into `/config/custom_components/bambu_lab`.
- Starts Home Assistant normally.

## Build and run

```bash
docker build -t ha-bambulab-home-assistant .

docker run -d \
  --name ha-bambulab \
  --network host \
  -e TZ=Etc/UTC \
  -e HA_BAMBULAB_REF=main \
  -v /path/to/ha-config:/config \
  ha-bambulab-home-assistant
```

## Unraid template

A ready-to-import Unraid template is provided at:

- `unraid/ha-bambulab-home-assistant.xml`

Before using, update `<Repository>` with your published image path.

## Environment variables

- `HA_BAMBULAB_REF` (default: `main`) - Branch or tag to install.
- `HA_BAMBULAB_REPO` (default: `https://github.com/greghesp/ha-bambulab.git`) - Integration repo.
- `HA_CONFIG_DIR` (default: `/config`) - Home Assistant config path inside container.

## Notes

- Host networking is recommended/expected for Home Assistant on Unraid.
- The integration is refreshed on every container start so updates are picked up automatically.
