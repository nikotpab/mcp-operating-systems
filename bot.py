import os
import subprocess
import asyncio
import json
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

TOKEN = os.environ.get("TELEGRAM_TOKEN")
TARGET_SERVER_CONFIG = "/app/mcp_config.json"
PROJECTS_DIR = "/app/projects"
MEMBERS, REFERENCE, ITEM_NAME, ITEM_COMMAND, ITEM_DESC = range(5)

os.makedirs(PROJECTS_DIR, exist_ok=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Ingresa los integrantes del taller:")
    return MEMBERS

async def receive_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['members'] = update.message.text
    context.user_data['items'] = []
    await update.message.reply_text("Por favor, envía el documento .docx de talleres pasados como referencia de estilo (fuentes, estructura):")
    return REFERENCE

async def receive_reference(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.document or not update.message.document.file_name.endswith('.docx'):
        await update.message.reply_text("Por favor envía un archivo .docx válido.")
        return REFERENCE
        
    doc_file = await update.message.document.get_file()
    ref_path = f"{PROJECTS_DIR}/referencia.docx"
    await doc_file.download_to_drive(ref_path)
    context.user_data['reference_doc'] = ref_path
    
    await update.message.reply_text("Documento guardado. Ahora ingresa el nombre del primer ítem, o 'FIN' para terminar:")
    return ITEM_NAME

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
            result = await session.call_tool(tool_name, arguments)
            return result

async def execute_and_screenshot(command: str, image_filename: str):
    xterm_process = subprocess.Popen([
        "xterm",
        "-geometry", "80x24",
        "-e",
        f"{command}; sleep 3"
    ])
    await asyncio.sleep(2)
    subprocess.run(["gnome-screenshot", "-f", image_filename], check=False)
    try:
        xterm_process.terminate()
    except Exception:
        pass

async def receive_item_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.upper() == "FIN":
        await update.message.reply_text("Generando documento final...")
        
        doc_filename = f"{PROJECTS_DIR}/taller_final.docx"
        
        await run_mcp_tool("create_docx", {
            "title": "Taller Final",
            "members": context.user_data['members'],
            "filename": doc_filename,
            "template": context.user_data.get('reference_doc')
        })
        
        for item in context.user_data['items']:
            content_text = f"Ítem: {item['name']}\nComando ejecutado:\n{item['command']}\n\nDescripción:\n{item['desc']}"
            await run_mcp_tool("append_content", {
                "filename": doc_filename,
                "content": content_text,
                "image_path": item['image']
            })
            
        await update.message.reply_document(document=open(doc_filename, "rb"))
        return ConversationHandler.END

    context.user_data['current_item'] = {"name": text}
    await update.message.reply_text(f"Ítem: {text}. Ahora envía el comando técnico a ejecutar (ej. ls -la):")
    return ITEM_COMMAND

async def receive_item_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    command = update.message.text.strip()
    context.user_data['current_item']['command'] = command
    await update.message.reply_text("Copiado. Ahora escribe la descripción técnica de este ítem:")
    return ITEM_DESC

async def receive_item_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    desc = update.message.text.strip()
    context.user_data['current_item']['desc'] = desc
    
    current_item = context.user_data['current_item']
    item_index = len(context.user_data['items']) + 1
    image_filename = f"{PROJECTS_DIR}/screenshot_{item_index}.png"
    
    await update.message.reply_text(f"Ejecutando comando '{current_item['command']}' y tomando captura...")
    await execute_and_screenshot(current_item['command'], image_filename)
    
    current_item['image'] = image_filename
    context.user_data['items'].append(current_item)
    
    await update.message.reply_text(f"Ítem {item_index} guardado. Ingresa el nombre del siguiente ítem, o 'FIN':")
    return ITEM_NAME

def main():
    app = Application.builder().token(TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MEMBERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_members)],
            REFERENCE: [MessageHandler(filters.Document.ALL, receive_reference)],
            ITEM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_item_name)],
            ITEM_COMMAND: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_item_command)],
            ITEM_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_item_desc)],
        },
        fallbacks=[]
    )
    app.add_handler(conv_handler)
    app.run_polling()

if __name__ == "__main__":
    main()
