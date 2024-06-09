import asyncio
from aiocryptopay import AioCryptoPay, Networks
from db import Session, User, WithdrawalRequest

# Replace with your Crypto Pay API token
crypto = AioCryptoPay(token='', network=Networks.MAIN_NET) 

async def process_auto_withdrawal(withdrawal_request_id, user_id, amount, wallet, send_message_function):
    try:
        # Create a check
        check = await crypto.create_check(
            asset='TON',  # Specify TON as the asset
            amount=amount,
            pin_to_user_id=user_id  # User can activate the check
        )

        if check.status == 'error':
            raise Exception(f"Ошибка при создании чека: {check.error_message}")

        # Update withdrawal request status in the database
        session = Session()
        withdrawal_request = session.query(WithdrawalRequest).get(withdrawal_request_id)
        withdrawal_request.status = "выполнено"
        session.commit()
        session.close()

        # Send messages with check activation link
        user = session.query(User).get(user_id)
        private_channel_id = -1002166916382  # Your private channel ID

        user_message = f"Эй, Дрочер! Для вывода {amount} TON активируй чек:\n{check.bot_check_url}" 
        channel_message = f"Чек на {amount} TON создан для пользователя @{user.username}.\nID запроса: {withdrawal_request_id}"

        await send_message_function(user_id, user_message)
        await send_message_function(private_channel_id, channel_message)

    except Exception as e:
        # Error handling
        print(f"Ошибка при автоматическом выводе: {e}")
        # (Optional) Log the error and notify the administrator