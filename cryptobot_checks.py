from aiocryptopay import AioCryptoPay, Networks

# Replace with your actual Crypto Pay API token
crypto = AioCryptoPay(token='', network=Networks.MAIN_NET) #MAIN_NET для мейн сети, TEST_NET для тест сети.

async def get_cryptobot_checks():
    checks = await crypto.get_checks(status='active')  # Получаем только активные чеки
    if checks:
        checks_info = "\n".join([
            f"ID: {check.check_id}, Статус: {check.status}, Сумма: {check.amount} {check.asset}"
            for check in checks
        ])
        return checks_info
    else:
        return None

async def delete_check(check_id):
    return await crypto.delete_check(check_id=check_id)

async def delete_all_checks():
    checks = await crypto.get_checks(status='active')  # указываем статус "active"
    if checks:
        for check in checks:
            await delete_check(check.check_id)