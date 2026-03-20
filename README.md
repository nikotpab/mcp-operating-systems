# Autonomous AI Orchestrator

## Overview
This repository contains a fully autonomous AI orchestration system designed to process, execute, and document academic software engineering tasks on native Ubuntu Linux environments. Driven by a Telegram Bot Interface and the Gemini 3 Flash language model, the orchestrator parses long-form natural language requirements into sequential executable commands. It captures terminal interactions visually, repairs dependency errors dynamically, and synthesizes final formatted academic reports using the Model Context Protocol (MCP).

## Architecture

The system is composed of several interdependent modules handling distinct responsibilities:

1. **Telegram Bot Interface (`bot.py`)**: The primary communication and state-management layer. Built with `python-telegram-bot` and `asyncio`, it handles concurrent user workflows, receives reference documents, and streams execution states back to the user via status heartbeats.
2. **LLM Planner (Gemini)**: Utilizes `gemini-3-flash` to semantically dissect unstructured text prompts into a strictly structured JSON pipeline. The model differentiates between direct `bash` executable tasks and theoretical questions that require localized context awareness.
3. **Execution Environment**:
   * Commands are written to temporary shell scripts and launched natively via `xterm`, providing isolated, visible execution pathways in the host Ubuntu X11 session.
   * `scrot` silently captures precise window telemetry of the exact execution results.
   * Command execution runs within a strict 45-second `asyncio.wait_for` lifecycle to prevent terminal locks caused by missing interactive inputs (e.g., `sudo` password prompts).
4. **Auto-Recovery Loop**: Failed execution hooks return deterministic exit codes that immediately trigger a sub-routine (`apt-get --fix-broken install`) designed to restore and retry system stability without human intervention.
5. **Document Generation (MCP-Doc)**: Integrates the `MeterLong/MCP-Doc` server over standard IO via FastMCP. A pre-flight `read_docx` call extracts typography and hierarchical styling parameters from a user-provided template, matching the final generated file format perfectly to academic requirements without manual typesetting.

## Setup Requirements

* native Ubuntu environment (access to X11 for `xterm` and `scrot`).
* Python 3.11+.
* `git`, `xterm`, `scrot` installed globally via `apt`.

## Installation

1. Clone the repository natively:
   ```bash
   git clone <repository-url>
   cd MCP-sistemas-operacionales
   ```

2. Create and activate a Python virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Install the Python dependencies:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. Clone the local MCP Document Server dependency:
   ```bash
   git clone https://github.com/MeterLong/MCP-Doc.git
   ```

5. Configure Environmental Variables:
   Create a `.env` file in the root directory and define the following variables securely:
   ```env
   TELEGRAM_TOKEN=your_telegram_bot_token_here
   GEMINI_API_KEY=your_gemini_api_key_here
   ```

## Usage

Start the main orchestration loop:
```bash
source .venv/bin/activate
python bot.py
```

Interact with the bot on Telegram by sending the `/start` command. Follow the multi-step initialization (providing team members, sending the reference `.docx` template, and pasting the full workshop text). The bot will output diagnostic heartbeats every 60 seconds outlining log integrity and execution progress.

## Security

API Keys and tokens are explicitly externalized to physical `.env` files. The `.gitignore` policy strictly prohibits the commitment of environmental credentials and local dependency caches to remote upstream repositories.

## Operations
System faults and dependency crashes encountered during the automated orchestration are transparently piped to the Telegram thread. The 45-second timeout safeguard allows the user to manually intervene, passing `skip` or arbitrary raw bash instructions via chat to rescue stuck execution tasks dynamically.
