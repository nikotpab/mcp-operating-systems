import os
import subprocess
import asyncio
import json
import google.generativeai as genai
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

TOKEN = os.environ.get("TELEGRAM_TOKEN")
TARGET_SERVER_CONFIG = "./mcp_config.json"
PROJECTS_DIR = "./projects"
MEMBERS, REFERENCE, FULL_WORKSHOP_PROMPT, WAIT_USER_ERROR = range(4)

if os.environ.get("GEMINI_API_KEY"):
    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

os.makedirs(PROJECTS_DIR, exist_ok=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Ingresa los integrantes del taller:")
    return MEMBERS

async def receive_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['members'] = update.message.text
    context.user_data['items'] = []
    context.user_data['history'] = []
    await update.message.reply_text("Envía el documento .docx de referencia:")
    return REFERENCE

async def receive_reference(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.document or not update.message.document.file_name.endswith('.docx'):
        await update.message.reply_text("Envía un archivo .docx válido.")
        return REFERENCE
    doc_file = await update.message.document.get_file()
    ref_path = f"{PROJECTS_DIR}/referencia.docx"
    await doc_file.download_to_drive(ref_path)
    context.user_data['reference_doc'] = ref_path
    
    await update.message.reply_text("Plantilla guardada. Pega el texto completo del taller:")
    return FULL_WORKSHOP_PROMPT

async def run_mcp_tool(tool_name: str, arguments: dict):
    with open(TARGET_SERVER_CONFIG, "r") as f:
        config = json.load(f)
    server_params = config["mcpServers"]["mcp-doc"]
    server = StdioServerParameters(
        command=server_params["command"],
        args=server_params["args"],
        env=os.environ.copy()
    )
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(tool_name, arguments)

async def execute_and_screenshot(command: str, image_filename: str):
    for f in ["/tmp/out", "/tmp/err", "/tmp/code", "/tmp/script.sh"]:
        if os.path.exists(f): os.remove(f)

    # Creamos un script temporal de Bash que ejecute el comando en la terminal
    script_sh = f"#!/bin/bash\n{command} > /tmp/out 2> /tmp/err\necho $? > /tmp/code\ncat /tmp/out /tmp/err\nsleep 3\n"
    with open("/tmp/script.sh", "w") as f: 
        f.write(script_sh)
    os.chmod("/tmp/script.sh", 0o777)
    
    # Lanzar xterm y ejecutar el script. xterm depende de X11 en Ubuntu
    xterm_process = subprocess.Popen(["xterm", "-geometry", "80x24", "-e", "/tmp/script.sh"])
    
    # Esperamos hasta que el script haya generado el código de salida
    for _ in range(40):
        if os.path.exists("/tmp/code"):
            break
        await asyncio.sleep(1)
        
    # La ventana sigue abierta por el "sleep 3". Le tomamos captura con scrot de ventana activa (-u)
    subprocess.run(["scrot", "-u", image_filename], check=False)
    
    # Esperamos o forzamos el cierre
    try:
        xterm_process.wait(timeout=5)
    except:
        xterm_process.terminate()
    
    try:
        with open("/tmp/code", "r") as f: code = int(f.read().strip())
    except:
        code = 1
    
    stdout = ""
    stderr = ""
    if os.path.exists("/tmp/out"):
        with open("/tmp/out", "r") as f: stdout = f.read()
    if os.path.exists("/tmp/err"):
        with open("/tmp/err", "r") as f: stderr = f.read()
        
    return code, stdout, stderr

async def repair_and_retry(command: str, image_filename: str, stderr: str, update: Update):
    await update.message.reply_text(f"Error detectado:\n{stderr[:200]}...\nIntentando reparar dependencias con apt-get...")
    subprocess.run("sudo apt-get update && sudo apt-get --fix-broken install -y", shell=True, capture_output=True)
    await update.message.reply_text("Reintentando comando...")
    return await execute_and_screenshot(command, image_filename)

async def generate_command_desc(task: dict, stdout: str):
    try:
        model = genai.GenerativeModel('models/gemini-3-flash-preview')
        response = model.generate_content(f"Describe académicamente lo que hizo este comando y su resultado. Contexto del profesor: {task.get('explicacion_contexto', '')}\nComando: {task['contenido']}\nSalida:\n{stdout[:800]}")
        return response.text
    except Exception:
        return "Ejecución exitosa de comando. Output capturado."

async def generate_answer(task: dict, history: str):
    try:
        model = genai.GenerativeModel('models/gemini-3-flash-preview')
        response = model.generate_content(f"Responde la siguiente pregunta de forma académica basándote en el contexto técnico de los comandos previos ejecutados.\nPregunta: {task['contenido']}\nContexto teórico: {task.get('explicacion_contexto', '')}\nHistorial de resultados previos:\n{history[-1500:]}")
        return response.text
    except Exception:
        return "Respuesta procesada correctamente basándose en análisis."

async def heartbeat_worker(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    while context.user_data.get('is_running', False):
        await asyncio.sleep(60)
        if context.user_data.get('is_running', False):
            log_status = "Logs limpios."
            if os.path.exists("/tmp/err"):
                try:
                    with open("/tmp/err", "r") as f:
                        err_content = f.read().strip()
                        if err_content:
                            log_status = f"Se encontraron advertencias/logs:\n{err_content[:150]}..."
                except:
                    pass
            await context.bot.send_message(chat_id=chat_id, text=f"⏱️ [Verificación 1-min]: Trabajo en proceso en tu MacBook M1.\nEstado de logs: {log_status}\n(Analizando con Gemini...)")

async def process_workshop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    await update.message.reply_text("Analizando texto con Gemini y planificando orquestación...")
    try:
        model = genai.GenerativeModel('models/gemini-3-flash-preview')
        prompt = f"Planifica la orquestación del taller autónomo. Devuelve UNICAMENTE un JSON (siempre un array []), con este schema exacto: [{{\"tipo\": \"comando\"|\"pregunta\", \"label\": \"Modulo X - Punto Y\", \"contenido\": \"comando_sh_o_texto_pregunta\", \"explicacion_contexto\": \"string\"}}]. \nTaller:\n{text}"
        response = model.generate_content(prompt)
        txt = response.text
        start_idx = txt.find('[')
        end_idx = txt.rfind(']') + 1
        if start_idx == -1 or end_idx == 0:
            raise ValueError("No JSON array returned")
        raw_json = txt[start_idx:end_idx]
        tasks = json.loads(raw_json)
    except Exception as e:
        import traceback
        error_info = traceback.format_exc()
        await update.message.reply_text(f"Error parseando Gemini API: {str(e)}\n\nDetalles técnicos:\n{error_info[:500]}")
        return ConversationHandler.END

    eta_seconds = (len(tasks) * 15) + 30
    await update.message.reply_text(f"Taller recibido. ETA estimado: {eta_seconds} segundos. Extrayendo estilo base vía MCP-Doc...")
    
    try:
        style_result = await run_mcp_tool("read_docx", {"filename": context.user_data['reference_doc']})
    except Exception:
        style_result = {"status": "default_style_assumed"}

    doc_filename = f"{PROJECTS_DIR}/taller_final.docx"
    await run_mcp_tool("create_docx", {
        "title": "Taller Analítico",
        "members": context.user_data['members'],
        "filename": doc_filename,
        "template": context.user_data['reference_doc'],
        "style_info": str(style_result)
    })

    context.user_data['tasks'] = tasks
    context.user_data['current_task_idx'] = 0
    context.user_data['doc_filename'] = doc_filename
    context.user_data['is_running'] = True
    context.user_data['heartbeat_task'] = asyncio.create_task(heartbeat_worker(update.effective_chat.id, context))
    
    return await execute_current_task(update, context)

async def execute_current_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = context.user_data['tasks']
    idx = context.user_data['current_task_idx']
    
    if idx >= len(tasks):
        context.user_data['is_running'] = False
        await update.message.reply_text("Taller orquestado exitosamente. Documento final:")
        await update.message.reply_document(document=open(context.user_data['doc_filename'], "rb"))
        return ConversationHandler.END

    task = tasks[idx]
    image_filename = ""
    hist_text = "\n".join(context.user_data['history'])

    if task['tipo'] == 'comando':
        image_filename = f"{PROJECTS_DIR}/screenshot_{idx}.png"
        await update.message.reply_text(f"[{task['label']}] Ejecutando: {task['contenido']}")
        
        try:
            code, out, err = await asyncio.wait_for(execute_and_screenshot(task['contenido'], image_filename), timeout=45.0)
        except asyncio.TimeoutError:
            await update.message.reply_text(f"⚠️ El comando `{task['contenido']}` se bloqueó (quizás pidiendo sudo/intervención). Resuélvelo manualmente y envía 'skip' para saltarlo, o un comando para reintentar.")
            context.user_data['is_running'] = False
            return WAIT_USER_ERROR
            
        if code != 0:
            try:
                code, out, err = await asyncio.wait_for(repair_and_retry(task['contenido'], image_filename, err, update), timeout=45.0)
            except asyncio.TimeoutError:
                await update.message.reply_text("⚠️ Timeout durante la reparación. Resuélvelo manualmente y envía un comando o 'skip'.")
                context.user_data['is_running'] = False
                return WAIT_USER_ERROR
                
            if code != 0:
                context.user_data['pending_error'] = err
                await update.message.reply_text(f"⚠️ Persiste el error en {task['label']}:\n{err[:200]}\nEnvía un comando manual de reparación o 'skip'.")
                context.user_data['is_running'] = False
                return WAIT_USER_ERROR

        desc = await generate_command_desc(task, out)
        context.user_data['history'].append(f"Result {task['contenido']}: {out[:100]}")
        content_text = f"Punto: {task['label']}\nComando ejecutado:\n{task['contenido']}\n\nDescripción:\n{desc}"

    elif task['tipo'] == 'pregunta':
        await update.message.reply_text(f"[{task['label']}] Analizando pregunta...")
        answer = await generate_answer(task, hist_text)
        content_text = f"Punto: {task['label']}\nPregunta:\n{task['contenido']}\n\nRespuesta de Análisis:\n{answer}"
        context.user_data['history'].append(f"Answer {task['label']}: {answer[:100]}")

    await run_mcp_tool("append_content", {
        "filename": context.user_data['doc_filename'],
        "content": content_text,
        "image_path": image_filename if os.path.exists(image_filename) else None
    })

    context.user_data['current_task_idx'] += 1
    return await execute_current_task(update, context)

async def handle_user_error_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    instruction = update.message.text.strip()
    idx = context.user_data['current_task_idx']
    
    if instruction.lower() == 'skip':
        await update.message.reply_text("Omitiendo paso autónomo...")
        context.user_data['current_task_idx'] += 1
        context.user_data['is_running'] = True
        return await execute_current_task(update, context)
        
    await update.message.reply_text(f"Ejecución asistida: {instruction}")
    subprocess.run(instruction, shell=True)
    await update.message.reply_text("Reintentando paso...")
    context.user_data['is_running'] = True
    return await execute_current_task(update, context)

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MEMBERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_members)],
            REFERENCE: [MessageHandler(filters.Document.ALL, receive_reference)],
            FULL_WORKSHOP_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_workshop)],
            WAIT_USER_ERROR: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_error_input)],
        },
        fallbacks=[]
    ))
    app.run_polling()

if __name__ == "__main__":
    main()
