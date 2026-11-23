"""Webhook for a WhatsApp provider. pip install fastapi uvicorn; uvicorn server:app
Payload shapes differ by provider (Twilio, Turn.io, Meta Cloud API): adapt parse() only."""
from fastapi import FastAPI, Request
from adcop.bot import handle_message
app = FastAPI()
def parse(body: dict):            # TODO: map your provider's payload to (phone, text)
    return body["from"], body["text"]
@app.post("/webhook")
async def webhook(req: Request):
    phone, text = parse(await req.json())
    return {"reply": handle_message(phone, text)}   # send this back via the provider's send API
