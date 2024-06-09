import asyncio
from aiocryptopay import AioCryptoPay, Networks  # Import Invoice directly

# Replace with your actual Crypto Pay API token
crypto = AioCryptoPay(token='1', network=Networks.MAIN_NET)  #MAIN_NET для мейн сети, TEST_NET для тест сети

loop = asyncio.get_event_loop()  # Get the event loop for asynchronous operations

async def create_invoice(amount, asset='TON'): 
    invoice = await crypto.create_invoice(amount=amount, asset=asset)
    return invoice

async def get_invoice_status(invoice_id):
    invoices = await crypto.get_invoices(invoice_ids=[invoice_id])
    if invoices:
        return invoices[0].status
    return None