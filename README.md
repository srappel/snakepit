# snakepit

A lightweight, portable JupyterLab environment for Python experiments, managed with uv.

## Setup

Install `uv` if needed:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then clone and sync the environment:

```bash
git clone git@github.com:srappel/snakepit.git
cd snakepit
uv sync
```

## Launch

```bash
uv run jupyter lab
```

On WSL launch with no browser option:

```bash
./lab.sh
```
