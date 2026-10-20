# SeparationScreen Brasil

App desktop de separação de cores para estamparia/serigrafia (PySide6 + motor FAV8+).

## Conteúdo deste pacote

| Pasta / arquivo | Função |
|-----------------|--------|
| `Separatio Clone FAV8/` | UI do app (`scf8/`, `run.py`, guia HTML) |
| `packages/` | Motor e libs (`fav8_plus`, `separate_channels`, `prepress`, `core`, `image`, `infra`) |
| `apps/desktop_qt/` | Presenters, canvas e docks usados pela UI |
| `pontos_de_trabalho/motor_travado.json` | Hash do motor travado |
| `abrir_separationscreen_brasil.bat` | Atalho Windows |
| `pyproject.toml` | Dependências Python |

**Não incluso (de propósito):** testes, agentes, prints de referência, `build`/`dist`/`entulho`, `.venv`, documentação de pesquisa.

## Requisitos

- Python **3.11+**
- Windows (UI Qt)

## Setup

```powershell
cd "C:\Users\PC-R7 5700\Desktop\para o git"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -e .
```

## Abrir o app (forma final — executável)

Duplo clique em:

- `Abrir SeparationScreen Brasil.bat`

Ou direto:

- `dist\SeparationScreen_Brasil_BETA_0.01\SeparationScreen_Brasil_BETA_0.01.exe`

(A pasta `_internal` precisa ficar junto do `.exe`.)

## Abrir pelo código (desenvolvimento)

```powershell
.\abrir_separationscreen_brasil.bat
```

Ou:

```powershell
.\.venv\Scripts\python.exe "Separatio Clone FAV8\run.py"
```

## Regra do motor (importante)

O motor em `packages/skills/fav8_plus/`, `packages/prepress/` e `packages/skills/separate_channels/` está **travado**.

- Não editar esses caminhos sem autorização explícita **"EDITAR MOTOR"**.
- UI e restante do app ficam em `Separatio Clone FAV8/` e `apps/` / `packages/core|image|infra`.
- Após edição autorizada do motor: `python pontos_de_trabalho/travar_motor.py`

## Nome do produto

Na interface: **SeparationScreen Brasil** (`scf8/branding.py`).
