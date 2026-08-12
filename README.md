# snakepit

A lightweight, portable Python environment for experiments, managed with uv and ready for JupyterLab or VS Code.

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

## JupyterLab

```bash
uv run jupyter lab
```

Launch script that points to the settings directory:

```bash
./lab.sh
```

## VS Code

Install the recommended Python and Jupyter extensions when VS Code prompts you, then run:

```bash
./code.sh
```

The launcher runs `uv sync --locked` before opening the repository. The committed workspace settings select `.venv/bin/python`, so Python files, terminals, and notebook kernels use the same environment defined by `pyproject.toml` and `uv.lock`.

You can also open the repository with `code .` after running `uv sync`; the workspace settings still select the project environment.
