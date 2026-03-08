import os
import requests
from fastapi import FastAPI, Request, HTTPException
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = FastAPI()

line_bot_api = LineBotApi(os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])

HF_SPACE_URL = os.environ["HF_SPACE_URL"]

conversation_history = {}

@app.get("/")
def root():
    return {"status": "LINE Bot is running!"}

@app.post("/webhook")
async def webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")
    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_text = event.message.text

    if user_id not in conversation_history:
        conversation_history[user_id] = []

    conversation_history[user_id].append({
        "role": "user",
        "content": user_text
    })

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        *conversation_history[user_id]
    ]

    response = requests.post(
        f"{HF_SPACE_URL}/chat",
        json={"messages": messages, "max_tokens": 500},
        timeout=60
    )

    bot_reply = response.json()["response"]

    conversation_history[user_id].append({
        "role": "assistant",
        "content": bot_reply
    })

    if len(conversation_history[user_id]) > 20:
        conversation_history[user_id] = conversation_history[user_id][-20:]

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=bot_reply)
    )
