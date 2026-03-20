import os
import subprocess
import asyncio
import json
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_TELEGRAM_TOKEN")
TARGET_SERVER_CONFIG = "/app/mcp_config.json"
PROJECTS_DIR = "/app/projects"
MEMBERS, WORKSHOP = range(2)

os.makedirs(PROJECTS_DIR, exist_ok=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Ingresa los integrantes del taller:")
    return MEMBERS

async def receive_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['members'] = update.message.text
    context.user_data['items'] = []
    await update.message.reply_text("Ingresa el primer enunciado o 'FIN' para terminar:")
    return WORKSHOP

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

async def capture_screenshot(filename: str):
    subprocess.run(["gnome-screenshot", "-f", filename], check=True)

async def handle_workshop_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text.strip().upper() == "FIN":
        await update.message.reply_text("Generando documento...")
        doc_filename = f"{PROJECTS_DIR}/taller_final.docx"
        
        await run_mcp_tool("create_docx", {
            "title": "Taller",
            "members": context.user_data['members'],
            "filename": doc_filename
        })
        
        for item in context.user_data['items']:
            await run_mcp_tool("append_content", {
                "filename": doc_filename,
                "content": item['text'],
                "image_path": item['image']
            })
            
        await update.message.reply_document(document=open(doc_filename, "rb"))
        return ConversationHandler.END

    item_index = len(context.user_data['items']) + 1
    image_filename = f"{PROJECTS_DIR}/screenshot_{item_index}.png"
    
    await capture_screenshot(image_filename)
    context.user_data['items'].append({"text": text, "image": image_filename})
    
    await update.message.reply_text(f"Ítem {item_index} registrado con captura. Ingresa el siguiente enunciado o 'FIN':")
    return WORKSHOP

def main():
    app = Application.builder().token(TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MEMBERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_members)],
            WORKSHOP: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_workshop_item)],
        },
        fallbacks=[]
    )
    app.add_handler(conv_handler)
    app.run_polling()

if __name__ == "__main__":
    main()
