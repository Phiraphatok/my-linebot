import os
import time
import requests
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from pathlib import Path
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = FastAPI()

line_bot_api = LineBotApi(os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])

HF_SPACE_URL = os.environ["HF_SPACE_URL"]

conversation_history = {}


@app.get("/", response_class=HTMLResponse)
def root():
    html = Path("chat.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/health")
def health():
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


def call_hf_api(messages: list, max_retries: int = 3) -> str:
    for attempt in range(max_retries):
        try:
            response = requests.post(
                f"{HF_SPACE_URL}/chat",
                json={"messages": messages, "max_tokens": 150},
                timeout=180  # CPU ช้า ให้เวลา 3 นาที
            )

            # Log สำหรับ debug
            print(f"[HF API] Attempt {attempt + 1} | Status: {response.status_code}")
            print(f"[HF API] Raw response: {response.text[:300]}")

            # HF Space กำลัง wake up
            if response.status_code == 503:
                wait = 10 * (attempt + 1)
                print(f"[HF API] Space sleeping, retrying in {wait}s...")
                time.sleep(wait)
                continue

            response.raise_for_status()

            # Response ว่างเปล่า
            if not response.text.strip():
                print("[HF API] Empty response received")
                time.sleep(5)
                continue

            data = response.json()

            # รองรับหลาย key ที่ HF Space อาจ return
            bot_reply = (
                data.get("response") or
                data.get("output") or
                data.get("result") or
                data.get("text") or
                data.get("generated_text")
            )

            if bot_reply:
                return str(bot_reply)
            else:
                print(f"[HF API] Unexpected response format: {data}")
                return f"ขอโทษครับ ได้รับข้อมูลผิดรูปแบบ: {str(data)[:100]}"

        except requests.exceptions.Timeout:
            print(f"[HF API] Timeout on attempt {attempt + 1}")
            if attempt < max_retries - 1:
                time.sleep(5)
            else:
                return "ขอโทษครับ ระบบใช้เวลานานเกินไป กรุณาลองใหม่สักครู่ครับ"

        except requests.exceptions.JSONDecodeError as e:
            print(f"[HF API] JSON decode error: {e} | Response: {response.text[:200]}")
            return "ขอโทษครับ เกิดข้อผิดพลาดในการอ่านข้อมูล กรุณาลองใหม่ครับ"

        except requests.exceptions.ConnectionError as e:
            print(f"[HF API] Connection error: {e}")
            if attempt < max_retries - 1:
                time.sleep(5)
            else:
                return "ขอโทษครับ ไม่สามารถเชื่อมต่อกับระบบได้ กรุณาลองใหม่ครับ"

        except Exception as e:
            print(f"[HF API] Unexpected error: {e}")
            return f"เกิดข้อผิดพลาดที่ไม่คาดคิดครับ"

    return "ขอโทษครับ ระบบไม่พร้อมใช้งานในขณะนี้ กรุณาลองใหม่ภายหลังครับ"


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

    bot_reply = call_hf_api(messages)

    conversation_history[user_id].append({
        "role": "assistant",
        "content": bot_reply
    })

    # เก็บแค่ 20 messages ล่าสุด
    if len(conversation_history[user_id]) > 20:
        conversation_history[user_id] = conversation_history[user_id][-20:]

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=bot_reply)
    )
