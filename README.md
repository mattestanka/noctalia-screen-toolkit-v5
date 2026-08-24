# Noctalia Screen Toolkit v5

Personal Noctalia v5 fork of `alexander/screen-toolkit`, carrying forward the
Mango and NVIDIA capture fixes from
[`mattestanka/noctalia-screen-toolkit`](https://github.com/mattestanka/noctalia-screen-toolkit).

The publishable plugin source is in `screen-toolkit/`; `catalog.toml` exposes it
as `mattestanka/screen-toolkit`.

## Development

```sh
noctalia plugins lint screen-toolkit
./tests/run.sh
```

For local testing, place or symlink `screen-toolkit/` at:

```text
~/.local/share/noctalia/plugins/screen-toolkit
```

Then enable `mattestanka/screen-toolkit` and replace any bindings that still
target `alexander/screen-toolkit`.

